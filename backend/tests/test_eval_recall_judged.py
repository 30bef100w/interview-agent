import json
from pathlib import Path

from app.services.official_recall_eval import metrics_at_k

QRELS = Path(__file__).resolve().parents[1] / "data" / "eval" / "judged_qrels.json"


def test_judged_qrels_cover_twenty_queries():
    data = json.loads(QRELS.read_text(encoding="utf-8"))
    assert "qrels" in data
    assert len(data["qrels"]) == 20
    assert "a01" in data["qrels"]
    assert "j01" in data["qrels"]


def test_metrics_top48_counts_hits():
    rel = {"a", "b", "c"}
    ranked = ["a", "x", "b"] + ["z"] * 45
    m = metrics_at_k(ranked, rel, 48)
    assert m["hits"] == 2
    assert abs(m["P"] - 2 / 48) < 1e-9
