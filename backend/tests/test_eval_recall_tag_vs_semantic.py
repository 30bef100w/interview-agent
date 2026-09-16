"""金标集：标签召回 vs 语义召回。"""
import json
from pathlib import Path

from app.services import knowledge_retrieval as kr
from app.services.recall_eval import load_golden, retrieve_tag_ab, score_hits
from app.services.semantic_retrieval import apply_role_filter, question_corpus_text, retrieve_ngram

DEMO = Path(__file__).resolve().parents[1] / "data" / "eval" / "demo_questions.jsonl"


def _load_demo() -> list[dict]:
    rows = []
    with open(DEMO, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def test_golden_file_is_well_formed():
    golden = load_golden()
    assert len(golden["cases"]) >= 10
    ids = [c["id"] for c in golden["cases"]]
    assert len(ids) == len(set(ids))
    for case in golden["cases"]:
        assert case["query"]["query_text"]
        assert case["query"]["target_role"]
        assert "want" in case and "forbid" in case


def test_demo_bank_survives_noise_filter():
    rows = _load_demo()
    assert len(rows) >= 12
    noisy = [q["question"] for q in rows if kr._is_noisy(q)]
    assert noisy == []


def test_tag_filters_recsys_away_from_redis_cache(monkeypatch):
    questions = _load_demo()
    if hasattr(kr.load_questions, "cache_clear"):
        kr.load_questions.cache_clear()
    monkeypatch.setattr(kr, "load_questions", lambda: questions)
    case = next(c for c in load_golden()["cases"] if c["id"] == "recsys_no_redis_leak")
    hits = retrieve_tag_ab(case["query"], top_n=6)
    s = score_hits(hits, case, 6)
    assert s["n"] >= 1
    assert (s["role_leak"] or 0) <= 0.34
    assert (s["forbid_keyword_hit"] or 0) <= 0.34
    assert (s["role_precision"] or 0) >= 0.66


def test_semantic_can_hit_paraphrase_without_scene_tags(monkeypatch):
    questions = _load_demo()
    monkeypatch.setattr(kr, "load_questions", lambda: questions)
    from app.services import semantic_retrieval as sr

    monkeypatch.setattr(sr, "load_questions", lambda: questions)
    sr._ngram_index.cache_clear()
    case = next(c for c in load_golden()["cases"] if c["id"] == "paraphrase_no_tag_words")
    hits = retrieve_ngram(case["query"], top_n=6)
    s = score_hits(hits, case, 6)
    assert s["n"] >= 1
    assert (s["want_keyword_hit"] or 0) >= 0.3
    texts = " ".join(question_corpus_text(h).lower() for h in hits[:4])
    assert "知识片段" in texts or "相近" in texts or "向量" in texts or "ann" in texts


def test_hybrid_drops_cross_role_after_semantic(monkeypatch):
    questions = _load_demo()
    monkeypatch.setattr(kr, "load_questions", lambda: questions)
    from app.services import semantic_retrieval as sr

    monkeypatch.setattr(sr, "load_questions", lambda: questions)
    sr._ngram_index.cache_clear()
    case = next(c for c in load_golden()["cases"] if c["id"] == "agent_no_seckill")
    raw = retrieve_ngram(case["query"], top_n=18)
    filtered = apply_role_filter(raw, ["agent_dev"])
    assert filtered
    assert all("agent_dev" in (h.get("roles") or []) for h in filtered)
    seckill = [h for h in filtered if "秒杀" in (h.get("question") or "")]
    assert seckill == []
