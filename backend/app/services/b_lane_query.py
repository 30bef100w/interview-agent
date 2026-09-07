"""B 路检索 query：从简历闭集勾选本场场景 + 技术点。

岗/企仍由词典映射，本模块不改 roles。LLM 只能从预置场景表与简历 skills/tech_stack 中勾选。
失败时退回规则兜底，不阻塞开练。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_SCENES_PATH = Path(__file__).resolve().parents[2] / "data" / "project_scenes.json"

MAX_SCENES = 4
MAX_SKILLS = 6

B_LANE_QUERY_SYSTEM = """你是面试检索规划助手，只为本场 B 路（问法/项目深挖）挑选检索标签。

铁律：
1. 目标岗位由系统给定，你不能改岗位、不能改公司
2. scenes 只能从【可选场景】里勾，skills 只能从【可选技术点】里勾；禁止发明简历没有的技术
3. 按【目标岗位】筛选：面 Agent 就留 RAG/LangChain/工具调用，丢掉本场无关的 Redis/秒杀/JVM
4. 面 Java 后端则保留中间件与并发，丢掉纯 CV/推荐算法词
5. 可少选，不要为凑数全选；scenes 最多 4 个，skills 最多 6 个
6. 只输出 JSON

Respond ONLY with this JSON schema:
{
  "scenes": ["预置场景名"],
  "skills": ["简历里出现过的技术点"]
}"""


@lru_cache(maxsize=1)
def preset_scene_names() -> tuple[str, ...]:
    try:
        raw = json.loads(_SCENES_PATH.read_text(encoding="utf-8"))
    except OSError:
        return ()
    names: list[str] = []
    for group in ("business_scenes", "tech_scenes"):
        for item in raw.get(group) or []:
            name = str(item.get("name") or "").strip()
            if name:
                names.append(name)
    return tuple(names)


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        s = str(raw or "").strip()
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def collect_resume_scenes(profile: dict | None) -> list[str]:
    allowed = {n.casefold(): n for n in preset_scene_names()}
    found: list[str] = []
    for p in (profile or {}).get("projects") or []:
        for x in p.get("scene_tags") or []:
            s = str(x).strip()
            if not s:
                continue
            canon = allowed.get(s.casefold())
            found.append(canon or s)
    return _dedupe_keep_order(found)


def collect_resume_skills(profile: dict | None) -> list[str]:
    items: list[str] = []
    for s in (profile or {}).get("skills") or []:
        items.append(str(s))
    for p in (profile or {}).get("projects") or []:
        for s in p.get("tech_stack") or p.get("tech") or []:
            items.append(str(s))
    return _dedupe_keep_order(items)


def _clip_scenes(raw: list[Any], allowed: list[str]) -> list[str]:
    allow_map = {a.casefold(): a for a in allowed}
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        token = str(item or "").strip()
        if not token:
            continue
        hit = allow_map.get(token.casefold())
        if not hit:
            for name in allowed:
                if token in name or name in token:
                    hit = name
                    break
        if not hit:
            continue
        key = hit.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
        if len(out) >= MAX_SCENES:
            break
    return out


def _clip_skills(raw: list[Any], allowed: list[str]) -> list[str]:
    allow_map = {a.casefold(): a for a in allowed}
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        token = str(item or "").strip()
        if not token:
            continue
        hit = allow_map.get(token.casefold())
        if not hit:
            low = token.casefold()
            for name in allowed:
                nlow = name.casefold()
                if len(nlow) >= 3 and (nlow in low or low in nlow):
                    hit = name
                    break
        if not hit:
            continue
        key = hit.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
        if len(out) >= MAX_SKILLS:
            break
    return out


def allowed_scene_universe(profile: dict | None) -> list[str]:
    """只允许简历里已有的场景（归一到预置名）；不能凭空加物联网等。"""
    return collect_resume_scenes(profile)


def fallback_b_lane_query(profile: dict | None) -> tuple[list[str], list[str]]:
    scenes = collect_resume_scenes(profile)[:MAX_SCENES]
    skills = collect_resume_skills(profile)[:MAX_SKILLS]
    return scenes, skills


def clip_b_lane_query(
    payload: dict | None,
    *,
    profile: dict | None,
) -> tuple[list[str], list[str]]:
    allowed_scenes = allowed_scene_universe(profile)
    allowed_skills = collect_resume_skills(profile)
    data = payload if isinstance(payload, dict) else {}
    scenes = _clip_scenes(list(data.get("scenes") or []), allowed_scenes)
    skills = _clip_skills(list(data.get("skills") or []), allowed_skills)
    return scenes, skills


def build_b_lane_user(profile: dict | None, target_role: str, role_ids: list[str]) -> str:
    scenes = collect_resume_scenes(profile)
    skills = collect_resume_skills(profile)
    preset = "、".join(preset_scene_names())
    projects = []
    for p in (profile or {}).get("projects") or []:
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        tech = "、".join(
            str(x).strip() for x in (p.get("tech_stack") or p.get("tech") or []) if str(x).strip()
        )
        tags = "、".join(
            str(x).strip() for x in (p.get("scene_tags") or []) if str(x).strip()
        )
        projects.append(f"- {name}｜技术：{tech or '（无）'}｜场景：{tags or '（无）'}")
    return (
        f"【目标岗位】{target_role or '（未选）'}\n"
        f"【岗位 id】{'、'.join(role_ids) or '（无）'}\n"
        f"【可选场景（仅简历已标注）】{'、'.join(scenes) or '（无，可只选技术点）'}\n"
        f"【预置场景表（不得选用未出现在简历中的项）】{preset or '（无）'}\n"
        f"【可选技术点】{'、'.join(skills) or '（无）'}\n"
        "【简历项目】\n"
        + ("\n".join(projects) if projects else "（无）")
    )
