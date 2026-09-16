"""召回对照评测：金标、标签 A/B、命中打分。脚本与单测共用。"""
from __future__ import annotations

import json
from pathlib import Path

from app.services import knowledge_retrieval as kr
from app.services.job_roles import resolve_company_id, resolve_target_roles

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "data" / "eval" / "recall_golden.json"


def load_golden(path: Path | None = None) -> dict:
    with open(path or GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


def retrieve_tag_ab(query: dict, top_n: int) -> list[dict]:
    """贴近生产 A+B：A 路岗位硬过滤，B 路场景加分（有 scenes 时）。"""
    roles = resolve_target_roles(query.get("target_role") or "")
    company = resolve_company_id(query.get("target_company") or "")
    skills = list(query.get("skills") or [])
    scenes = list(query.get("scenes") or [])
    pool = max(30, top_n)
    a = kr.retrieve(
        roles=roles or None,
        company=company,
        skills=skills[:6],
        scenes=None,
        top_n=top_n,
        pool_size=pool,
    )
    b: list[dict] = []
    if scenes:
        b = kr.retrieve(
            roles=roles or None,
            company=company,
            skills=skills,
            scenes=scenes,
            category="project",
            top_n=max(4, top_n // 2),
            pool_size=pool,
        )
    seen: set[str] = set()
    merged: list[dict] = []
    for h in a + b:
        key = kr._question_norm(h)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(h)
        if len(merged) >= top_n:
            break
    return merged


def _blob(h: dict) -> str:
    return f"{h.get('question') or ''} {h.get('answer') or ''}".lower()


def score_hits(hits: list[dict], case: dict, top_n: int) -> dict:
    want = case.get("want") or {}
    forbid = case.get("forbid") or {}
    prefer_roles = set(want.get("roles") or [])
    forbid_roles = set(forbid.get("roles") or [])
    want_kw = [k.lower() for k in (want.get("keywords") or [])]
    forbid_kw = [k.lower() for k in (forbid.get("keywords") or [])]
    prefer_scenes = set(want.get("scenes") or [])
    ranked = hits[:top_n]
    n = len(ranked)
    empty = {
        "n": 0,
        "role_precision": 0.0 if prefer_roles else None,
        "role_leak": 1.0 if forbid_roles else None,
        "want_keyword_hit": 0.0 if want_kw else None,
        "forbid_keyword_hit": 1.0 if forbid_kw else None,
        "scene_precision": 0.0 if prefer_scenes else None,
        "quality": 0.0,
        "titles": [],
    }
    if n == 0:
        return empty

    role_ok = role_leak = kw_hit = kw_bad = scene_ok = 0
    titles: list[str] = []
    for h in ranked:
        titles.append(str(h.get("question") or "")[:48])
        roles = set(h.get("roles") or [])
        scenes = set((h.get("business_scene") or []) + (h.get("tech_scene") or []))
        text = _blob(h)
        if prefer_roles and roles & prefer_roles:
            role_ok += 1
        if forbid_roles and roles & forbid_roles:
            role_leak += 1
        if want_kw and any(k in text for k in want_kw):
            kw_hit += 1
        if forbid_kw and any(k in text for k in forbid_kw):
            kw_bad += 1
        if prefer_scenes and scenes & prefer_scenes:
            scene_ok += 1

    role_p = (role_ok / n) if prefer_roles else None
    leak = (role_leak / n) if forbid_roles else None
    want_h = (kw_hit / n) if want_kw else None
    forbid_h = (kw_bad / n) if forbid_kw else None
    scene_p = (scene_ok / n) if prefer_scenes else None

    parts: list[float] = []
    if role_p is not None:
        parts.append(role_p)
    if want_h is not None:
        parts.append(want_h)
    if leak is not None:
        parts.append(1.0 - leak)
    if forbid_h is not None:
        parts.append(1.0 - forbid_h)
    quality = sum(parts) / len(parts) if parts else 0.0
    return {
        "n": n,
        "role_precision": role_p,
        "role_leak": leak,
        "want_keyword_hit": want_h,
        "forbid_keyword_hit": forbid_h,
        "scene_precision": scene_p,
        "quality": quality,
        "titles": titles,
    }
