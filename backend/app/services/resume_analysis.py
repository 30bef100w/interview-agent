"""简历智能分析：调用 LLM 输出结构化建议。"""
from __future__ import annotations

from app.services.llm.client import OpenAiLlm

SYSTEM = """你是资深技术招聘与简历顾问。请基于候选人简历文本给出可执行的优化建议。
只输出 JSON，字段：
{
  "summary": "一段总评",
  "strengths": ["优点1", "优点2"],
  "risks": ["风险/短板1", "..."],
  "improvements": ["可落地修改建议1", "..."],
  "interview_focus": ["面试官可能深挖的点1", "..."],
  "score": 1-10 的整数（简历完成度/竞争力粗评）
}
不要编造简历中没有的经历。"""


def analyze_resume(raw_text: str, profile: dict | None = None) -> dict:
    llm = OpenAiLlm()
    profile_snip = ""
    if profile:
        profile_snip = f"\n\n已抽取画像（可参考）：\n{profile}"
    user = f"简历原文：\n{raw_text[:12000]}{profile_snip}"
    data = llm.chat_json(SYSTEM, user)
    return {
        "summary": str(data.get("summary") or ""),
        "strengths": list(data.get("strengths") or [])[:8],
        "risks": list(data.get("risks") or [])[:8],
        "improvements": list(data.get("improvements") or [])[:10],
        "interview_focus": list(data.get("interview_focus") or [])[:8],
        "score": int(float(data.get("score") or 0)),
    }
