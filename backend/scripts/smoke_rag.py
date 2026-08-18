"""检索注入冒烟：真实 LLM，验证 target_role 统领 + 检索素材 + 拷打链 + 计划。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.interviewer_engine import InterviewEngine  # noqa: E402
from app.services.llm.client import OpenAiLlm  # noqa: E402

PROFILE = {
    "name": "张三",
    "skills": ["Java", "Spring Boot", "Redis", "MySQL"],
    "projects": [
        {
            "name": "校园二手交易平台",
            "role": "后端开发",
            "tech_stack": ["Spring Boot", "Redis", "MySQL"],
            "highlights": ["Redis 预扣解决超卖", "Lua 脚本保证原子性"],
            "dig_points": ["库存预扣方案", "缓存一致性"],
            "scene_tags": ["外卖/本地生活", "高并发", "缓存"],
        },
        {
            "name": "AI 面试模拟器",
            "role": "全栈",
            "tech_stack": ["LangChain", "LangGraph", "FastAPI"],
            "highlights": ["多智能体编排", "RAG"],
            "dig_points": ["智能体状态机", "对拍判题"],
            "scene_tags": ["AI 应用/对话机器人", "AI/RAG/Agent"],
        },
    ],
    "experience_years": "应届",
}
RESUME_RAW = "张三，XX大学计算机专业。项目1：校园二手交易平台（Spring Boot+Redis），解决库存超卖。项目2：AI 面试模拟器（LangChain+LangGraph）。"


def main() -> int:
    llm = OpenAiLlm()
    engine = InterviewEngine(llm)

    # 场景 A：选 Agent 岗 → 应统领全局（计划应以 Agent 为主，检索素材含 Agent 题）
    state, opening = engine.create(
        1, RESUME_RAW, PROFILE, 8, "full", "full",
        target_role="AI Agent 开发", target_company="",
    )
    print("======== 场景 A：目标岗位 = AI Agent 开发 ========")
    print("\n-- 检索素材（前 6 条）--")
    for line in state.retrieved_material.splitlines()[:6]:
        print(" ", line[:100])
    print(f"\n-- 拷打链 {len(state.project_chains)} 个项目 --")
    for pc in state.project_chains:
        print(f"  {pc['project']}: {len(pc['chains'])} 条链")
        for c in pc["chains"][:2]:
            print(f"    trigger: {c['trigger'][:40]}")
            print(f"    question: {c['question'][:60]}")
    print("\n-- 计划话题 --")
    for q in state.plan:
        print(f"  [{q['type']}] {q['topic']}")
    print("素材含 Agent:", "Agent" in state.retrieved_material or "智能体" in state.retrieved_material or "LangChain" in state.retrieved_material)

    # 场景 B：选 Java 后端 → 计划应以 Java 为主
    state2, _ = engine.create(
        2, RESUME_RAW, PROFILE, 8, "full", "full",
        target_role="Java 后端", target_company="腾讯",
    )
    print("\n======== 场景 B：目标岗位 = Java 后端 + 腾讯 ========")
    for line in state2.retrieved_material.splitlines()[:4]:
        print(" ", line[:100])
    print("-- 计划话题 --")
    for q in state2.plan:
        print(f"  [{q['type']}] {q['topic']}")
    print("素材含腾讯:", "tencent" in state2.retrieved_material or "腾讯" in state2.retrieved_material)
    return 0


if __name__ == "__main__":
    sys.exit(main())
