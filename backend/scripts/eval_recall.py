"""召回质量评估：多个典型画像场景，检查命中质量/多样性/去重效果。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import knowledge_retrieval as kr  # noqa: E402

SCENES = [
    ("Java 后端 + 黑马点评", "Java 后端", "", ["Java", "Spring Boot", "Redis", "MySQL"], ["外卖/本地生活", "高并发", "缓存"]),
    ("AI Agent 开发 + AI 面试项目", "AI Agent 开发", "", ["Python", "LangChain", "LangGraph", "FastAPI"], ["AI 应用/对话机器人", "AI/RAG/Agent"]),
    ("前端 + 管理后台", "Web 前端", "", ["React", "TypeScript", "Vite"], ["后台管理/企业系统"]),
    ("Go 后端 + 腾讯", "Go 后端", "腾讯", ["Go", "Gin", "gRPC"], []),
    ("数据开发 + 大数据项目", "数据开发 / 大数据", "", ["Spark", "Flink", "Hive"], ["大数据/数据平台", "大数据处理"]),
]


def norm(s: str) -> str:
    import re
    return re.sub(r"\W+", "", (s or "").lower())


def main() -> int:
    for label, role, company, skills, scenes in SCENES:
        print("=" * 60)
        print(f"场景：{label}（role={role}, company={company or '无'}）")
        hits = kr.retrieve(
            roles=kr.load_questions() and [role],  # placeholder
            company=company or None,
            skills=skills,
            scenes=scenes,
            top_n=8,
        )
        # 上面的 roles 用文本不对，重新用岗位 id
        from app.services.job_roles import infer_roles

        rid = infer_roles({"text": role})
        hits = kr.retrieve(
            roles=rid,
            company=company or None,
            skills=skills,
            scenes=scenes,
            top_n=8,
        )
        print(f"  召回 {len(hits)} 条")
        for i, h in enumerate(hits, 1):
            tags = f"[{h.get('company') or '无企'} | {'/'.join((h.get('roles') or [])[:2]) or '无岗'} | {h.get('era') or '未知'}]"
            print(f"  {i}. {tags} {h['question'][:52]}")
        # 多样性：岗位/企业去重后的覆盖
        roles_covered = len({tuple((h.get('roles') or [])[:1]) for h in hits})
        print(f"  → 岗位覆盖 {roles_covered} 种，era 最新：{max((h.get('era') or '0000') for h in hits)}")

    # 去重效果：同样的画像，第一次 vs 带 asked_norms
    print("=" * 60)
    print("去重效果：同一画像召回两次（第二次带 asked 集合）")
    hits1 = kr.retrieve(roles=["agent_dev"], skills=["LangChain"], scenes=["AI/RAG/Agent"], top_n=8)
    asked = {norm(h["question"]) for h in hits1[:4]}
    hits2 = kr.retrieve(roles=["agent_dev"], skills=["LangChain"], scenes=["AI/RAG/Agent"], asked_norms=asked, top_n=8)
    dup = sum(1 for h in hits2 if norm(h["question"]) in asked)
    print(f"  第一次: {[h['question'][:20] for h in hits1[:4]]}")
    print(f"  第二次(去重): {[h['question'][:20] for h in hits2[:4]]}")
    print(f"  重复数: {dup}/8（应为 0-1）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
