"""正式召回评测：查询集契约 + 金标/指标（不依赖 4.5 万题库）。"""
from app.services.official_recall_eval import (
    build_qrels,
    is_relevant,
    load_official,
    metrics_at_k,
    ranked_ids,
)


def test_official_queries_are_resume_scale():
    spec = load_official()
    queries = spec["queries"]
    ids = [q["id"] for q in queries]
    assert len(queries) >= 50
    assert len(ids) == len(set(ids))
    for q in queries:
        assert q["query_text"]
        assert q["target_role"]
        assert q["roles"]
        assert q["positives"]
        assert int(q.get("min_positives") or 1) >= 1


def test_relevance_independent_of_retriever_scores():
    spec = {
        "roles": ["agent_dev"],
        "positives": ["langgraph"],
        "min_positives": 1,
        "negatives": ["秒杀超卖"],
    }
    hit = {
        "question": "LangGraph 节点怎么传状态",
        "answer": "用 state schema。",
        "roles": ["agent_dev"],
    }
    miss_role = {
        "question": "LangGraph 节点怎么传状态",
        "answer": "用 state schema。",
        "roles": ["java_backend"],
    }
    miss_kw = {
        "question": "Redis 缓存击穿",
        "answer": "互斥锁。",
        "roles": ["agent_dev"],
    }
    leak = {
        "question": "LangGraph 结合秒杀超卖怎么设计",
        "answer": "不要混岗。",
        "roles": ["agent_dev"],
    }
    untagged = {
        "question": "LangGraph checkpoint 怎么落盘",
        "answer": "sqlite。",
        "roles": [],
    }
    assert is_relevant(hit, spec)
    assert not is_relevant(miss_role, spec)
    assert not is_relevant(miss_kw, spec)
    assert not is_relevant(leak, spec)
    assert is_relevant(untagged, spec)


def test_qrels_and_metrics_on_tiny_bank():
    questions = [
        {"question": "LangGraph 状态机", "answer": "graph", "roles": ["agent_dev"]},
        {"question": "秒杀超卖 Lua", "answer": "stock", "roles": ["java_backend"]},
        {"question": "无关题", "answer": "x", "roles": ["agent_dev"]},
    ]
    queries = [
        {
            "id": "q1",
            "roles": ["agent_dev"],
            "positives": ["langgraph"],
            "min_positives": 1,
            "negatives": ["秒杀超卖"],
        }
    ]
    qrels = build_qrels(questions, queries)
    rel = qrels["q1"]
    assert len(rel) == 1
    ranked = ranked_ids(questions)
    m8 = metrics_at_k(ranked, rel, 8)
    assert m8["hits"] == 1
    assert m8["P"] == 1 / 3
    assert m8["R"] == 1.0
    assert m8["RR"] == 1.0
    assert m8["Success"] == 1.0
