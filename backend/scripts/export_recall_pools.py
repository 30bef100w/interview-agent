"""导出人工标注用 pooling：标签 Top48 ∪ 语义 Top48。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import knowledge_retrieval as kr  # noqa: E402
from app.services import semantic_retrieval as sr  # noqa: E402
from app.services.job_roles import resolve_target_roles  # noqa: E402
from app.services.official_recall_eval import doc_id, retrieve_tag_score  # noqa: E402
from app.services.semantic_retrieval import apply_role_filter, retrieve_ngram  # noqa: E402

QUERIES = Path(__file__).resolve().parents[1] / "data" / "eval" / "judged_queries.json"
OUT = Path(__file__).resolve().parents[1] / "logs" / "eval_recall_pools.json"
K = 48


def main() -> int:
    spec = json.loads(QUERIES.read_text(encoding="utf-8"))
    kr.load_questions.cache_clear()
    sr._ngram_index.cache_clear()
    n = len(kr.load_questions())
    print(f"题库 {n}  查询 {len(spec['queries'])}  pool K={K}")
    rows = []
    for i, q in enumerate(spec["queries"], 1):
        tag = retrieve_tag_score(q, K)
        sem = retrieve_ngram(q, top_n=K)
        roles = resolve_target_roles(q.get("target_role") or "")
        hyb = apply_role_filter(sem, roles)[:K]
        tag_ids = [doc_id(h) for h in tag if doc_id(h)]
        sem_ids = [doc_id(h) for h in sem if doc_id(h)]
        seen: dict[str, dict] = {}
        for src, hits in (("tag", tag), ("semantic", sem)):
            for rank, h in enumerate(hits, 1):
                key = doc_id(h)
                if not key:
                    continue
                item = seen.setdefault(
                    key,
                    {
                        "id": key,
                        "question": str(h.get("question") or "")[:160],
                        "in_tag": False,
                        "in_semantic": False,
                        "tag_rank": None,
                        "semantic_rank": None,
                    },
                )
                item[f"in_{src}"] = True
                item[f"{src}_rank"] = rank
        pool = list(seen.values())
        print(f"[{i}/{len(spec['queries'])}] {q['id']}  pool={len(pool)}  tag={len(tag)} sem={len(sem)}")
        rows.append(
            {
                "id": q["id"],
                "query_text": q["query_text"],
                "intent": q.get("intent") or "",
                "target_role": q.get("target_role"),
                "tag_ids": tag_ids,
                "semantic_ids": sem_ids,
                "hybrid_ids": [doc_id(h) for h in hyb if doc_id(h)],
                "pool": pool,
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"k": K, "queries": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
