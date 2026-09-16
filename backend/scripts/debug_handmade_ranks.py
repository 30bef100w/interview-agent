"""看手选题在 n-gram / 标签路排第几，以及 Top15 实际题干。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import knowledge_retrieval as kr  # noqa: E402
from app.services.official_recall_eval import doc_id, retrieve_tag_score  # noqa: E402
from app.services.semantic_retrieval import retrieve_ngram  # noqa: E402

HANDMADE = Path(__file__).resolve().parents[1] / "data" / "eval" / "handmade_qrels.json"
ONLY = sys.argv[1:] or ["hashmap", "spring_cycle", "langgraph_state", "prompt_injection"]


def main() -> None:
    spec = json.loads(HANDMADE.read_text(encoding="utf-8"))
    kr.load_questions.cache_clear()
    questions = kr.load_questions()
    by_norm = {doc_id(q): q for q in questions if doc_id(q)}
    want = {q["id"]: q for q in spec["queries"] if q["id"] in ONLY}
    for qid, q in want.items():
        rel = []
        for text in q["relevant_questions"]:
            key = kr._norm(text)
            if key in by_norm:
                rel.append((key, by_norm[key].get("question") or text))
        tag = retrieve_tag_score(q, 48)
        sem = retrieve_ngram({"query_text": q["query_text"]}, top_n=200)
        tag_pos = {doc_id(h): i + 1 for i, h in enumerate(tag)}
        sem_pos = {doc_id(h): i + 1 for i, h in enumerate(sem)}
        print("\n====", qid, "query:", q["query_text"])
        print("-- 手选题在两路的名次 (sem 看 Top200)")
        for key, title in rel:
            print(f"  tag={tag_pos.get(key, '-'):>4}  sem={sem_pos.get(key, '-'):>4}  {title[:70]}")
        print("-- tag Top12")
        for i, h in enumerate(tag[:12], 1):
            print(f"  T{i:02d}  {(h.get('question') or '')[:80]}")
        print("-- ngram Top12")
        for i, h in enumerate(sem[:12], 1):
            print(f"  S{i:02d}  {(h.get('question') or '')[:80]}")


if __name__ == "__main__":
    main()
