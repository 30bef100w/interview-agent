"""用手选测评集评测：金标是读过的题干列表，与检索器无关。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import knowledge_retrieval as kr  # noqa: E402
from app.services import semantic_retrieval as sr  # noqa: E402
from app.services.job_roles import resolve_target_roles  # noqa: E402
from app.services.official_recall_eval import doc_id, metrics_at_k, retrieve_tag_score  # noqa: E402
from app.services.semantic_retrieval import apply_role_filter, retrieve_ngram  # noqa: E402

HANDMADE = Path(__file__).resolve().parents[1] / "data" / "eval" / "handmade_qrels.json"
OUT = Path(__file__).resolve().parents[1] / "logs" / "eval_recall_handmade.json"
KS = (8, 32, 48)


def _fmt(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:.3f}"


def main() -> int:
    spec = json.loads(HANDMADE.read_text(encoding="utf-8"))
    kr.load_questions.cache_clear()
    sr._ngram_index.cache_clear()
    questions = kr.load_questions()
    by_norm = {doc_id(q): q for q in questions if doc_id(q)}
    print(f"题库 {len(questions)}  查询 {len(spec['queries'])}")

    per_query = []
    sums = {m: {f"{p}{k}": 0.0 for k in KS for p in ("P", "R", "h")} for m in ("tag", "semantic", "hybrid")}
    n_ok = 0
    for q in spec["queries"]:
        rel: set[str] = set()
        missing = []
        for text in q["relevant_questions"]:
            key = kr._norm(text)
            if key in by_norm:
                rel.add(key)
            else:
                missing.append(text[:80])
        if missing:
            print(f"!! {q['id']} 未在题库命中 {len(missing)} 条:")
            for m in missing:
                print("   -", m)
        if len(rel) < 3:
            print(f"SKIP {q['id']} 有效金标 {len(rel)}")
            continue
        tag = [doc_id(h) for h in retrieve_tag_score(q, 48) if doc_id(h)]
        # 语义路只吃面试问句，不把岗位名拼进去，否则 n-gram 会被「AI Agent 开发」带去框架对比题。
        sem_hits = retrieve_ngram({"query_text": q["query_text"]}, top_n=48)
        sem = [doc_id(h) for h in sem_hits if doc_id(h)]
        hyb = [
            doc_id(h)
            for h in apply_role_filter(sem_hits, resolve_target_roles(q.get("target_role") or ""))
            if doc_id(h)
        ]
        row = {"id": q["id"], "|Rel|": len(rel), "methods": {}}
        print(f"\n{q['id']}  |Rel|={len(rel)}  {q['query_text'][:36]}")
        for name, ranked in (("tag", tag), ("semantic", sem), ("hybrid", hyb)):
            at = {k: metrics_at_k(ranked, rel, k) for k in KS}
            row["methods"][name] = at
            for k in KS:
                sums[name][f"P{k}"] += at[k]["P"] or 0
                sums[name][f"R{k}"] += at[k]["R"] or 0
                sums[name][f"h{k}"] += at[k]["hits"]
            parts = [f"P@{k}={_fmt(at[k]['P'])}  hits@{k}={at[k]['hits']}  R@{k}={_fmt(at[k]['R'])}" for k in KS]
            print(f"  {name:9}  " + "  ".join(parts))
        per_query.append(row)
        n_ok += 1

    print("\n" + "=" * 72)
    print(f"手选测评集宏平均  n={n_ok}")
    summary = {}
    for name in ("tag", "semantic", "hybrid"):
        s = {f"{p}@{k}": sums[name][f"{p}{k}"] / n_ok for k in KS for p in ("P", "R")}
        for k in KS:
            s[f"hits@{k}"] = sums[name][f"h{k}"] / n_ok
        summary[name] = s
        parts = [f"P@{k}={_fmt(s[f'P@{k}'])}  hits@{k}={s[f'hits@{k}']:.2f}  R@{k}={_fmt(s[f'R@{k}'])}" for k in KS]
        print(f"  {name:9}  " + "  ".join(parts))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "n": n_ok,
                "summary": summary,
                "per_query": per_query,
                "resume_note": "金标为读题干手选的 related questions，不用岗位标签。",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("写到", OUT)
    return 0 if n_ok >= 10 else 3


if __name__ == "__main__":
    sys.exit(main())
