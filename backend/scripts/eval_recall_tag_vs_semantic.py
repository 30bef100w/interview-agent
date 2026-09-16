"""标签召回 vs 题面语义召回 对照评测。

默认跑内置 demo 题库（可复现、能看出差异）。对全量 questions_dedup.jsonl：

  python scripts/eval_recall_tag_vs_semantic.py --bank full

可选真正的 embedding 向量召回（需兼容 OpenAI embeddings 的模型，DeepSeek chat 通常没有该接口）：

  python scripts/eval_recall_tag_vs_semantic.py --bank demo --semantic embed --embed-model text-embedding-v3 --embed-base-url ... --embed-api-key ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import knowledge_retrieval as kr  # noqa: E402
from app.services import recall_eval  # noqa: E402
from app.services import semantic_retrieval as sr  # noqa: E402
from app.services.job_roles import resolve_target_roles  # noqa: E402
from app.services.recall_eval import retrieve_tag_ab, score_hits  # noqa: E402
from app.services.semantic_retrieval import apply_role_filter, retrieve_embed, retrieve_ngram  # noqa: E402

DEMO_BANK = Path(__file__).resolve().parents[1] / "data" / "eval" / "demo_questions.jsonl"
FULL_BANK = Path(__file__).resolve().parents[1] / "data" / "knowledge_base" / "questions_dedup.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def retrieve_semantic(query: dict, *, backend: str, top_n: int, args: argparse.Namespace) -> list[dict]:
    if backend == "embed":
        return retrieve_embed(
            query,
            top_n=top_n * 3,
            model=args.embed_model,
            base_url=args.embed_base_url,
            api_key=args.embed_api_key,
        )
    return retrieve_ngram(query, top_n=top_n * 3)


def _fmt(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:.2f}"


def mean(xs: list[float | None]) -> float | None:
    nums = [x for x in xs if x is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def install_bank(questions: list[dict]) -> None:
    kr.load_questions.cache_clear()
    kr.load_questions = lambda: questions  # type: ignore[method-assign]
    sr.load_questions = lambda: questions  # type: ignore[method-assign]
    sr._ngram_index.cache_clear()


def run(args: argparse.Namespace) -> int:
    golden = recall_eval.load_golden()
    if args.bank == "demo":
        questions = load_jsonl(DEMO_BANK)
        install_bank(questions)
        print(f"题库：demo ({len(questions)} 条)  {DEMO_BANK}")
    else:
        if not FULL_BANK.exists():
            print(f"找不到全量题库：{FULL_BANK}")
            print("请在有 questions_dedup.jsonl 的环境跑 --bank full，或先用 --bank demo。")
            return 2
        kr.load_questions.cache_clear()
        sr._ngram_index.cache_clear()
        n = len(kr.load_questions())
        print(f"题库：full ({n} 条)  {FULL_BANK}")

    top_n = args.top_n
    rows: list[dict] = []
    print()
    for case in golden["cases"]:
        query = case["query"]
        roles = resolve_target_roles(query.get("target_role") or "")
        tag_hits = retrieve_tag_ab(query, top_n)
        sem_raw = retrieve_semantic(query, backend=args.semantic, top_n=top_n, args=args)
        sem_hits = sem_raw[:top_n]
        hyb_hits = apply_role_filter(sem_raw, roles)[:top_n]

        tag_s = score_hits(tag_hits, case, top_n)
        sem_s = score_hits(sem_hits, case, top_n)
        hyb_s = score_hits(hyb_hits, case, top_n)
        rows.append({"id": case["id"], "expect": case.get("expect"), "tag": tag_s, "semantic": sem_s, "hybrid": hyb_s})

        print("=" * 72)
        print(f"{case['id']}  expect={case.get('expect')}  {case['title']}")
        print(
            f"  tag     quality={_fmt(tag_s['quality'])}  role_p={_fmt(tag_s['role_precision'])}  "
            f"leak={_fmt(tag_s['role_leak'])}  want={_fmt(tag_s['want_keyword_hit'])}  "
            f"forbid_kw={_fmt(tag_s['forbid_keyword_hit'])}"
        )
        print(
            f"  semantic quality={_fmt(sem_s['quality'])}  role_p={_fmt(sem_s['role_precision'])}  "
            f"leak={_fmt(sem_s['role_leak'])}  want={_fmt(sem_s['want_keyword_hit'])}  "
            f"forbid_kw={_fmt(sem_s['forbid_keyword_hit'])}"
        )
        print(
            f"  hybrid  quality={_fmt(hyb_s['quality'])}  role_p={_fmt(hyb_s['role_precision'])}  "
            f"leak={_fmt(hyb_s['role_leak'])}  want={_fmt(hyb_s['want_keyword_hit'])}  "
            f"forbid_kw={_fmt(hyb_s['forbid_keyword_hit'])}"
        )
        if args.verbose:
            print("  tag top:", " | ".join(tag_s["titles"][:4]))
            print("  sem top:", " | ".join(sem_s["titles"][:4]))

    def col(method: str, field: str) -> list[float | None]:
        return [r[method][field] for r in rows]

    print("=" * 72)
    print("汇总（越高越好，leak / forbid_kw 已在 quality 里按 1-x 计入）")
    for name, key in (("tag", "tag"), ("semantic", "semantic"), ("hybrid=语义+岗位硬过滤", "hybrid")):
        q = mean(col(key, "quality"))
        rp = mean(col(key, "role_precision"))
        leak = mean(col(key, "role_leak"))
        want = mean(col(key, "want_keyword_hit"))
        bad = mean(col(key, "forbid_keyword_hit"))
        print(
            f"  {name:24}  quality={_fmt(q)}  role_p={_fmt(rp)}  leak={_fmt(leak)}  "
            f"want={_fmt(want)}  forbid_kw={_fmt(bad)}"
        )

    tag_q = mean(col("tag", "quality")) or 0
    sem_q = mean(col("semantic", "quality")) or 0
    hyb_q = mean(col("hybrid", "quality")) or 0
    print()
    print("怎么读：")
    print("  · tag     = 现在线上的标签 A/B 召回")
    print("  · semantic = 只看题干/答案相似度（demo 默认 n-gram；--semantic embed 才是向量）")
    print("  · hybrid  = 语义扩召回后再用岗位硬过滤（设计文档里的二期接法）")
    if hyb_q >= tag_q and hyb_q >= sem_q:
        print("  → 这批金标上：语义扩召回 + 岗位硬门槛 综合最好，不宜用纯向量替换标签。")
    elif tag_q > sem_q:
        print("  → 这批金标上：标签路更稳（尤其防串岗）。语义适合补漏标/同义改写，不要单独上。")
    else:
        print("  → 这批金标上：纯语义相关度更高，但请看 leak：若串岗高则仍不能替换硬门槛。")

    out = Path(__file__).resolve().parents[1] / "logs" / "eval_recall_tag_vs_semantic.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "bank": args.bank,
        "semantic_backend": args.semantic,
        "top_n": top_n,
        "cases": rows,
        "summary": {
            "tag_quality": tag_q,
            "semantic_quality": sem_q,
            "hybrid_quality": hyb_q,
        },
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已写 {out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="标签召回 vs 语义召回对照评测")
    p.add_argument("--bank", choices=["demo", "full"], default="demo")
    p.add_argument("--semantic", choices=["ngram", "embed"], default="ngram")
    p.add_argument("--top-n", type=int, default=6)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--embed-model", default="text-embedding-3-small")
    p.add_argument("--embed-base-url", default=None)
    p.add_argument("--embed-api-key", default=None)
    args = p.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
