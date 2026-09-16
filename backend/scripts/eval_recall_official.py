"""正式召回评测：50 查询 × 全库规则金标，标签 vs 题面语义。

  python scripts/eval_recall_official.py --qrels-only
  python scripts/eval_recall_official.py
  python scripts/eval_recall_official.py --semantic embed --embed-model ... --embed-base-url ... --embed-api-key ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import knowledge_retrieval as kr  # noqa: E402
from app.services import semantic_retrieval as sr  # noqa: E402
from app.services.job_roles import resolve_target_roles  # noqa: E402
from app.services.official_recall_eval import (  # noqa: E402
    build_qrels,
    load_official,
    mean_field,
    metrics_at_k,
    ranked_ids,
    retrieve_tag_score,
)
from app.services.semantic_retrieval import apply_role_filter, retrieve_embed, retrieve_ngram  # noqa: E402

FULL_BANK = Path(__file__).resolve().parents[1] / "data" / "knowledge_base" / "questions_dedup.jsonl"
KS = (8, 20, 50)
MIN_REL = 3
MAX_REL = 400


def _fmt(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:.3f}"


def retrieve_semantic(query: dict, *, backend: str, top_n: int, args: argparse.Namespace) -> list[dict]:
    if backend == "embed":
        return retrieve_embed(
            query,
            top_n=top_n,
            model=args.embed_model,
            base_url=args.embed_base_url,
            api_key=args.embed_api_key,
        )
    return retrieve_ngram(query, top_n=top_n)


def main() -> int:
    p = argparse.ArgumentParser(description="正式召回评测（全库金标）")
    p.add_argument("--qrels-only", action="store_true")
    p.add_argument("--semantic", choices=["ngram", "embed"], default="ngram")
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument("--embed-model", default="text-embedding-3-small")
    p.add_argument("--embed-base-url", default=None)
    p.add_argument("--embed-api-key", default=None)
    args = p.parse_args()

    spec = load_official()
    queries = spec["queries"]
    if not FULL_BANK.exists():
        print(f"找不到全量题库：{FULL_BANK}")
        return 2

    kr.load_questions.cache_clear()
    sr._ngram_index.cache_clear()
    questions = kr.load_questions()
    print(f"题库 {len(questions)}  查询 {len(queries)}  语义={args.semantic}")

    qrels = build_qrels(questions, queries)
    kept: list[dict] = []
    dropped: list[tuple[str, int]] = []
    print("\n金标 |Rel|")
    for q in queries:
        n_rel = len(qrels[q["id"]])
        flag = "OK"
        if n_rel < MIN_REL:
            flag = "DROP<3"
            dropped.append((q["id"], n_rel))
        elif n_rel > MAX_REL:
            flag = "DROP>400"
            dropped.append((q["id"], n_rel))
        else:
            kept.append(q)
        print(f"  {q['id']:4}  |Rel|={n_rel:5d}  {flag}  {q['query_text'][:42]}")

    print(f"\n纳入宏平均：{len(kept)} / {len(queries)}  丢弃 {dropped}")
    qrels_out = Path(__file__).resolve().parents[1] / "logs" / "eval_recall_official_qrels.json"
    qrels_out.parent.mkdir(parents=True, exist_ok=True)
    qrels_out.write_text(
        json.dumps({k: sorted(v) for k, v in qrels.items()}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"qrels 已写 {qrels_out}")
    if args.qrels_only:
        return 0 if len(kept) >= 40 else 3

    top_n = args.top_n
    per_query: list[dict] = []
    method_rows: dict[str, list[dict]] = {"tag": [], "semantic": [], "hybrid": []}

    for i, q in enumerate(kept, 1):
        rel = qrels[q["id"]]
        print(f"\n[{i}/{len(kept)}] {q['id']}  |Rel|={len(rel)}")
        tag_hits = retrieve_tag_score(q, top_n)
        sem_hits = retrieve_semantic(q, backend=args.semantic, top_n=top_n, args=args)
        roles = resolve_target_roles(q.get("target_role") or "")
        hyb_hits = apply_role_filter(sem_hits, roles)
        ranked = {
            "tag": ranked_ids(tag_hits),
            "semantic": ranked_ids(sem_hits),
            "hybrid": ranked_ids(hyb_hits),
        }
        row = {"id": q["id"], "|Rel|": len(rel), "methods": {}}
        for name, ids in ranked.items():
            at = {k: metrics_at_k(ids, rel, k) for k in KS}
            row["methods"][name] = at
            method_rows[name].append({"id": q["id"], **at[8], "R20": at[20]["R"], "P20": at[20]["P"], "R50": at[50]["R"]})
            print(
                f"  {name:9}  P@8={_fmt(at[8]['P'])}  R@8={_fmt(at[8]['R'])}  "
                f"R@20={_fmt(at[20]['R'])}  Succ@8={_fmt(at[8]['Success'])}  MRR={_fmt(at[8]['RR'])}"
            )
        per_query.append(row)

    def slice_summary(ids: set[str]) -> dict:
        out: dict = {}
        n = 0
        for name in ("tag", "semantic", "hybrid"):
            rows = [r for r in method_rows[name] if r["id"] in ids]
            n = len(rows)
            out[name] = {
                "P@8": mean_field(rows, "P"),
                "R@8": mean_field(rows, "R"),
                "R@20": mean_field(rows, "R20"),
                "R@50": mean_field(rows, "R50"),
                "Success@8": mean_field(rows, "Success"),
                "MRR": mean_field(rows, "RR"),
            }
        out["n"] = n
        return out

    print("\n" + "=" * 72)
    print(f"宏平均  n={len(kept)}  K=8 对齐线上素材路  语义后端={args.semantic}")
    summary = {}
    for name in ("tag", "semantic", "hybrid"):
        rows = method_rows[name]
        summary[name] = {
            "P@8": mean_field(rows, "P"),
            "R@8": mean_field(rows, "R"),
            "R@20": mean_field(rows, "R20"),
            "R@50": mean_field(rows, "R50"),
            "Success@8": mean_field(rows, "Success"),
            "MRR": mean_field(rows, "RR"),
        }
        s = summary[name]
        print(
            f"  {name:9}  P@8={_fmt(s['P@8'])}  R@8={_fmt(s['R@8'])}  "
            f"R@20={_fmt(s['R@20'])}  R@50={_fmt(s['R@50'])}  "
            f"Succ@8={_fmt(s['Success@8'])}  MRR={_fmt(s['MRR'])}"
        )

    slices = {
        "agent_a01_a20": slice_summary({f"a{i:02d}" for i in range(1, 21)}),
        "java_j01_j10": slice_summary({f"j{i:02d}" for i in range(1, 11)}),
    }
    print("\n切片  Agent 查询 a01–a20")
    for name in ("tag", "semantic", "hybrid"):
        s = slices["agent_a01_a20"][name]
        print(
            f"  {name:9}  P@8={_fmt(s['P@8'])}  Succ@8={_fmt(s['Success@8'])}  MRR={_fmt(s['MRR'])}"
        )

    out = Path(__file__).resolve().parents[1] / "logs" / "eval_recall_official.json"
    payload = {
        "protocol": spec.get("protocol"),
        "bank_size": len(questions),
        "semantic_backend": args.semantic,
        "n_queries_total": len(queries),
        "n_queries_scored": len(kept),
        "dropped": dropped,
        "min_rel": MIN_REL,
        "max_rel": MAX_REL,
        "ks": list(KS),
        "summary": summary,
        "slices": slices,
        "per_query": per_query,
        "resume_note": (
            "标签路=线上 A/B 打分排序（不用题面向量）；"
            "语义路=题干+答案 n-gram 余弦（不是神经网络 embedding，除非 --semantic embed）；"
            "金标=岗位∩关键短语全库标注，与两路分数独立。"
        ),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已写 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
