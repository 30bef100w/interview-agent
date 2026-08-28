"""JD / 练习焦点检索加权词提取。"""
from app.services.recall_boost import build_recall_boost_terms


def test_build_recall_boost_terms_from_jd_and_focus():
    terms = build_recall_boost_terms(
        "负责 Java 后端开发，熟悉 Redis、Kafka、微服务",
        "重点考察缓存穿透与击穿",
    )
    low = {t.lower() for t in terms}
    assert "redis" in low or "kafka" in low
    assert any("缓存" in t or "redis" in t.lower() for t in terms)


def test_build_recall_boost_terms_empty():
    assert build_recall_boost_terms("", "") == []
    assert build_recall_boost_terms("   ", None) == []
