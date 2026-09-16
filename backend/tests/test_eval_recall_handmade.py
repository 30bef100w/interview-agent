"""手选测评集契约：金标是题干列表，不是岗位标签。"""
import json
from pathlib import Path

from app.services.official_recall_eval import metrics_at_k

QRELS = Path(__file__).resolve().parents[1] / "data" / "eval" / "handmade_qrels.json"


def test_handmade_qrels_are_question_lists_not_roles():
    data = json.loads(QRELS.read_text(encoding="utf-8"))
    queries = data["queries"]
    assert len(queries) >= 12
    ids = [q["id"] for q in queries]
    assert len(ids) == len(set(ids))
    for q in queries:
        assert q["query_text"]
        rel = q["relevant_questions"]
        assert len(rel) >= 8, q["id"]
        assert "positives" not in q
        assert all(isinstance(t, str) and len(t) >= 4 for t in rel)


def test_metrics_count_handmade_hits_at_48():
    rel = {"spring三级缓存", "hashmap树化"}
    ranked = ["无关"] * 47 + ["spring三级缓存"]
    m = metrics_at_k(ranked, rel, 48)
    assert m["hits"] == 1
    assert abs(m["P"] - 1 / 48) < 1e-9
    assert abs(m["R"] - 0.5) < 1e-9
