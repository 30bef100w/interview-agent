"""B 路闭集勾选 + 岗位硬门槛打分。"""
from app.services.b_lane_query import (
    clip_b_lane_query,
    collect_resume_skills,
    fallback_b_lane_query,
)
from app.services.knowledge_retrieval import _score_question


PROFILE = {
    "skills": ["LangChain", "FastAPI", "Redis"],
    "projects": [
        {
            "name": "深问",
            "tech_stack": ["DeepSeek", "LangChain"],
            "scene_tags": ["AI 应用/对话机器人", "AI/RAG/Agent"],
        },
        {
            "name": "知秦",
            "tech_stack": ["Redis"],
            "scene_tags": ["外卖/本地生活"],
        },
    ],
}


def test_clip_drops_invented_tags_and_keeps_resume_closed_set():
    scenes, skills = clip_b_lane_query(
        {
            "scenes": ["物联网/嵌入式", "AI/RAG/Agent", "并不存在的场景"],
            "skills": ["Kubernetes", "LangChain", "redis"],
        },
        profile=PROFILE,
    )
    assert "物联网/嵌入式" not in scenes
    assert "AI/RAG/Agent" in scenes
    assert "Kubernetes" not in skills
    assert "LangChain" in skills
    assert "Redis" in skills


def test_fallback_uses_resume_scenes_and_skills():
    scenes, skills = fallback_b_lane_query(PROFILE)
    assert "外卖/本地生活" in scenes
    assert "AI/RAG/Agent" in scenes
    assert "LangChain" in collect_resume_skills(PROFILE)
    assert skills[0] in collect_resume_skills(PROFILE)


def test_lane_b_role_is_hard_gate_not_style_score():
    roles = {"agent_dev"}
    off = _score_question(
        {
            "question": "Redis 缓存击穿怎么防",
            "answer": "互斥锁",
            "roles": ["java_backend"],
            "company": "bytedance",
        },
        roles,
        "bytedance",
        ["redis"],
        {"缓存"},
        None,
        recall_boost_terms=[],
        lane="b",
    )
    on = _score_question(
        {
            "question": "LangChain 工具失败如何重试",
            "answer": "budget 与降级",
            "roles": ["agent_dev"],
            "tech_scene": ["AI/RAG/Agent"],
        },
        roles,
        None,
        ["langchain"],
        {"AI/RAG/Agent"},
        None,
        recall_boost_terms=[],
        lane="b",
    )
    style_company = _score_question(
        {
            "question": "字节 Agent 岗常问的编排题",
            "answer": "无技术点",
            "roles": ["agent_dev"],
            "company": "bytedance",
        },
        roles,
        "bytedance",
        [],
        set(),
        None,
        recall_boost_terms=[],
        lane="b",
    )
    assert off == 0.0
    assert on > style_company
    assert on > 40
