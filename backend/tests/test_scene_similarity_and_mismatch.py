"""场景标签相似度 + 错标审核队列单测。"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.tag_mismatch import TagMismatchReview
from app.services import scene_tag_similarity as sts
from app.services import tag_mismatch_queue as tmq
from app.services.tag_mismatch_queue import enqueue_llm_filtered_hits, pending_count


@pytest.fixture
def mismatch_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    monkeypatch.setattr(tmq, "SessionLocal", Session)
    monkeypatch.setattr(tmq, "_append_jsonl", lambda _payload: None)
    monkeypatch.setattr(tmq, "_try_publish_rocketmq", lambda _payload: "")
    yield session
    session.close()


def test_exact_tag_similarity_is_one():
    assert sts.tag_pair_similarity("外卖/本地生活", "外卖/本地生活") == 1.0


def test_related_tags_via_keywords_score_high():
    sim = sts.tag_pair_similarity("AI 应用/对话机器人", "AI/RAG/Agent")
    assert sim >= 0.35


def test_unrelated_tags_score_low():
    sim = sts.tag_pair_similarity("物联网/嵌入式", "AI/RAG/Agent")
    assert sim < 0.35


def test_scene_tags_similarity_averages_best_match():
    resume = ["外卖/本地生活", "高并发"]
    question = ["外卖/本地生活", "缓存"]
    sim = sts.scene_tags_similarity(resume, question)
    assert sim >= 0.5


def test_scene_score_bonus_zero_below_threshold():
    bonus = sts.scene_score_bonus(
        ["物联网/嵌入式"],
        ["AI/RAG/Agent"],
        has_roles=True,
    )
    assert bonus == 0.0


def test_enqueue_llm_filtered_hits_dedupes(mismatch_db):
    hits = [
        {
            "question": "JVM 垃圾回收器有哪些？",
            "roles": ["java_backend"],
            "business_scene": ["后台管理/企业系统"],
            "category": "bagu",
        }
    ]
    n1 = enqueue_llm_filtered_hits(
        hits, roles=["agent_dev"], lane="role_filter", session_id=42
    )
    n2 = enqueue_llm_filtered_hits(
        hits, roles=["agent_dev"], lane="role_filter", session_id=43
    )
    assert n1 == 1
    assert n2 == 0
    row = mismatch_db.query(TagMismatchReview).first()
    assert row is not None
    assert row.lane == "role_filter"
    assert json.loads(row.target_roles) == ["agent_dev"]
    assert pending_count(mismatch_db) == 1
