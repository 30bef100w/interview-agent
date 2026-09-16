"""同一份简历：标签召回 vs 语义召回 并排对比。

用法:
  python scripts/compare_recall_resume.py path/to/profile.json [--top-n 8]

profile.json 模拟简历解析后的画像（字段与测评集 query 一致）:
{
  "target_role": "AI Agent 开发",
  "target_company": "",                  // 可选，如 "腾讯"
  "skills": ["Python", "FastAPI"],       // 简历技术栈
  "scenes": ["AI/RAG/Agent"],            // 可选，从预置场景列表选
  "query_text": "项目描述原文……"           // 语义路唯一输入，写成口语自然段
}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.job_roles import resolve_target_roles, role_name  # noqa: E402
from app.services.recall_eval import retrieve_tag_ab  # noqa: E402
from app.services.semantic_retrieval import apply_role_filter, retrieve_ngram  # noqa: E402


def _roles_label(h: dict) -> str:
    names = [role_name(r) for r in (h.get("roles") or [])]
    return "/".join(names[:3]) if names else "无标签"


def _fmt_hits(title: str, hits: list[dict]) -> list[str]:
    lines = [f"【{title}】{len(hits)} 题"]
    for i, h in enumerate(hits, 1):
        q = str(h.get("question") or "")[:52]
        lines.append(f"  {i:2}. [{_roles_label(h):<18}] {q}")
    return lines


def main() -> int:
    p = argparse.ArgumentParser(description="同一份简历对比标签/语义/hybrid 召回")
    p.add_argument("profile", help="简历画像 JSON 路径")
    p.add_argument("--top-n", type=int, default=8)
    args = p.parse_args()

    query = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    top_n = args.top_n
    roles = resolve_target_roles(query.get("target_role") or "")

    tag = retrieve_tag_ab(query, top_n)
    sem_raw = retrieve_ngram({"query_text": query.get("query_text") or ""}, top_n=top_n * 3)
    sem = sem_raw[:top_n]
    hyb = apply_role_filter(sem_raw, roles)[:top_n]

    print("=" * 72)
    print(f"岗位: {query.get('target_role') or '(未填)'}  ->  {roles or '(未解析出 role_id)'}")
    print(f"技能: {', '.join(query.get('skills') or []) or '(无)'}")
    print(f"场景: {', '.join(query.get('scenes') or []) or '(无)'}")
    print(f"题面: {query.get('query_text', '')[:80]}")
    print("=" * 72)

    for line in _fmt_hits("标签召回（生产 A/B 路）", tag):
        print(line)
    print()
    for line in _fmt_hits("语义召回（仅题面 n-gram）", sem):
        print(line)
    print()
    for line in _fmt_hits("hybrid（语义 + 岗位硬过滤）", hyb):
        print(line)

    def norm(h: dict) -> str:
        return str(h.get("question") or "").strip()

    tag_set = {norm(h) for h in tag}
    sem_set = {norm(h) for h in sem}
    hyb_set = {norm(h) for h in hyb}
    print()
    print("-" * 72)
    print(f"重叠: 标签∩语义 {len(tag_set & sem_set)}  标签∩hybrid {len(tag_set & hyb_set)}  语义∩hybrid {len(sem_set & hyb_set)}")
    print("怎么判: 哪条路的题更像对着这份简历出的？岗位串没串？")
    return 0


if __name__ == "__main__":
    sys.exit(main())
