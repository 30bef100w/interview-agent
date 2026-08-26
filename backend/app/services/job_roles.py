"""岗位分类与企业表：加载配置 + 从简历画像推断岗位。

数据文件：data/job_roles.json（岗位分级 + 技术栈关键词）、data/companies.json（企业表）。
推断规则：画像的技能/项目文本命中关键词 → 岗位。关键词设计避开歧义（如 Java 用 spring 系列，不用裸 "java"）。
"""
import json
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@lru_cache(maxsize=1)
def load_roles() -> dict:
    with open(_DATA_DIR / "job_roles.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_companies() -> dict:
    with open(_DATA_DIR / "companies.json", encoding="utf-8") as f:
        return json.load(f)


def all_roles() -> dict:
    """{role_id: {name, keywords}}"""
    return load_roles()["roles"]


def all_categories() -> dict:
    """{一级分类: [role_id, ...]}"""
    return load_roles()["categories"]


def role_name(role_id: str) -> str:
    return all_roles().get(role_id, {}).get("name", role_id)


def resolve_target_roles(target_role: str) -> list[str]:
    """把用户选择的目标岗位文案解析为知识库 role_id 列表。

    优先级：role_id 精确 → 岗位中文名精确 → 一级分类名 → 名称包含 → 关键词推断。
    例：
      - 「搜广推」→ [recsys]
      - 「后端开发」→ [java_backend, go_backend, ...]
      - 「Java 后端」→ [java_backend]
    """
    raw = (target_role or "").strip()
    if not raw:
        return []
    roles = all_roles()
    cats = all_categories()
    low = raw.lower()

    if raw in roles:
        return [raw]
    if low in {rid.lower() for rid in roles}:
        return [rid for rid in roles if rid.lower() == low]

    for rid, cfg in roles.items():
        if raw == cfg.get("name"):
            return [rid]

    if raw in cats:
        return list(cats[raw])

    contained: list[str] = []
    for rid, cfg in roles.items():
        name = str(cfg.get("name") or "")
        if raw in name or name in raw:
            contained.append(rid)
    if contained:
        return contained

    for cat_name, ids in cats.items():
        if raw in cat_name or cat_name in raw:
            return list(ids)

    return infer_roles({"text": raw})


def infer_roles(profile: dict) -> list[str]:
    """从简历画像（skills/projects/文本）推断岗位，按命中关键词数降序。"""
    text = json.dumps(profile, ensure_ascii=False).lower()
    hits: list[tuple[int, str]] = []
    for rid, cfg in all_roles().items():
        n = sum(1 for kw in cfg["keywords"] if kw.lower() in text)
        if n > 0:
            hits.append((n, rid))
    hits.sort(reverse=True)
    return [rid for _, rid in hits]


# 与目标岗位无关时降权（例：面 Agent 岗却主栈是 Java/Redis 的点评类项目）
_BACKEND_STACK_HINTS = (
    "redis",
    "spring",
    "springboot",
    "mybatis",
    "kafka",
    "rocketmq",
    "jvm",
    "分布式锁",
    "缓存击穿",
    "缓存穿透",
    "秒杀",
    "mysql",
    "微服务",
)
_AGENT_ROLE_IDS = frozenset({"agent_dev", "llm"})
_AGENT_SIGNAL_KEYWORDS = (
    "agent",
    "rag",
    "mcp",
    "langchain",
    "langgraph",
    "智能体",
    "大模型",
    "llm",
    "tool calling",
    "function calling",
    "向量",
    "embedding",
    "prompt",
    "多智能体",
)


def agent_signal_count(text: str) -> int:
    """项目/题签里与 Agent 应用相关的信号数。"""
    low = (text or "").lower()
    return sum(1 for k in _AGENT_SIGNAL_KEYWORDS if k in low)


def _project_text_blob(project: dict, profile: dict | None = None) -> str:
    parts = [json.dumps(project, ensure_ascii=False)]
    if profile:
        parts.append(json.dumps({"skills": profile.get("skills") or []}, ensure_ascii=False))
    return " ".join(parts).lower()


def _project_role_score(
    project: dict, role_ids: list[str], profile: dict | None = None
) -> float:
    """单项目与目标岗位的匹配分（越高越应优先深挖）。"""
    if not role_ids:
        return 0.0
    roles_cfg = all_roles()
    text = _project_text_blob(project, profile)
    score = 0.0
    for rid in role_ids:
        for kw in roles_cfg.get(rid, {}).get("keywords", []):
            if kw.lower() in text:
                score += 1.0
    agent_hits = agent_signal_count(text)
    backend_hits = sum(1 for kw in _BACKEND_STACK_HINTS if kw in text)
    primary = role_ids[0]
    if primary in _AGENT_ROLE_IDS:
        if agent_hits >= 1:
            # 混合栈：有 Agent 段落就按岗位可问，后端栈只轻微降权
            score += agent_hits * 0.6
            score -= 0.15 * backend_hits
            score = max(score, 0.55)
        else:
            score -= 0.45 * backend_hits
    elif primary == "java_backend":
        score += 0.3 * backend_hits
    return score


def project_role_score(
    project: dict, role_ids: list[str], profile: dict | None = None
) -> float:
    """项目与目标岗位的匹配分（公开接口）。"""
    return _project_role_score(project, role_ids, profile)


def rank_resume_projects(profile: dict, target_role: str = "") -> list[dict]:
    """按与【目标岗位】相关度排序简历项目（最相关在前；同分保持简历原序）。"""
    projects = [p for p in (profile.get("projects") or []) if str(p.get("name") or "").strip()]
    if not projects:
        return []
    role_ids = resolve_target_roles(target_role) if target_role else infer_roles(profile)[:3]
    scored = [
        (_project_role_score(p, role_ids, profile), i, p)
        for i, p in enumerate(projects)
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [p for _, _, p in scored]


def resume_project_names(profile: dict, target_role: str = "", limit: int = 3) -> list[str]:
    """岗位相关度排序后的项目名列表。"""
    return [
        str(p.get("name") or "").strip()
        for p in rank_resume_projects(profile, target_role)[:limit]
        if str(p.get("name") or "").strip()
    ]


def assess_resume_depth(profile: dict, target_role: str = "") -> dict:
    """结构化评估简历可深挖程度，供 Router/引擎决定项目 vs 八股比例。"""
    projects = [
        p for p in (profile.get("projects") or []) if str(p.get("name") or "").strip()
    ]
    role_ids = resolve_target_roles(target_role) if target_role else infer_roles(profile)[:3]

    depth_points = 0
    for p in projects:
        desc = str(p.get("desc") or p.get("description") or "")
        tech = [str(x) for x in (p.get("tech_stack") or p.get("tech") or []) if str(x).strip()]
        if len(desc) >= 60:
            depth_points += 1
        if len(desc) >= 150:
            depth_points += 1
        if len(tech) >= 3:
            depth_points += 1
        if any(k in desc for k in ("难点", "优化", "上线", "指标", "QPS", "延迟", "吞吐", "复盘")):
            depth_points += 1

    ranked = rank_resume_projects(profile, target_role)
    role_relevant = sum(1 for p in ranked[:3] if _project_role_score(p, role_ids) >= 1.0)
    skills_n = len(profile.get("skills") or [])
    exp_n = len(profile.get("internships") or profile.get("experiences") or profile.get("work") or [])

    score = min(
        100,
        len(projects) * 10 + depth_points * 8 + skills_n * 2 + exp_n * 12 + role_relevant * 10,
    )
    if score >= 65 and len(projects) >= 2 and role_relevant >= 1:
        tier = "rich"
    elif score >= 35 and (projects or skills_n >= 5):
        tier = "medium"
    else:
        tier = "thin"

    return {
        "score": score,
        "tier": tier,
        "project_count": len(projects),
        "role_relevant_projects": role_relevant,
        "depth_points": depth_points,
        "skills_count": skills_n,
        "experience_count": exp_n,
    }


def suggest_project_bagu_counts(budget: int, depth: dict) -> tuple[int, int]:
    """按简历深度给出项目/八股建议配额（引擎硬约束基准）。"""
    budget = max(2, int(budget))
    tier = str(depth.get("tier") or "medium")
    rel = int(depth.get("role_relevant_projects") or 0)
    if tier == "rich":
        project_n = max(2, round(budget * (0.58 if rel >= 2 else 0.5)))
    elif tier == "medium":
        project_n = max(2, round(budget * (0.45 if rel >= 1 else 0.38)))
    else:
        project_n = max(2, min(3, round(budget * 0.32)))
    project_n = min(project_n, budget - 1)
    return project_n, max(1, budget - project_n)


def _experience_items(profile: dict) -> list[dict]:
    """统一取出实习/工作经历条目。"""
    items: list[dict] = []
    for key in ("internships", "experiences", "work", "internship"):
        raw = profile.get(key)
        if isinstance(raw, list):
            items.extend(x for x in raw if isinstance(x, dict))
        elif isinstance(raw, dict):
            items.append(raw)
    return items


def assess_askable_project_capacity(
    profile: dict,
    target_role: str = "",
    project_chains: list[dict] | None = None,
) -> dict:
    """评估「岗位视角下简历项目/实习还有多少可问点」——分题策略的核心。

    原则：先列岗位可问的项目题，剩余轮次再用八股补。
    """
    role_ids = resolve_target_roles(target_role) if target_role else infer_roles(profile)[:3]
    askable: list[dict] = []

    for p in rank_resume_projects(profile, target_role)[:3]:
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        score = _project_role_score(p, role_ids, profile)
        desc = str(p.get("desc") or p.get("description") or "")
        agent_in_proj = agent_signal_count(_project_text_blob(p, profile)) >= 1
        backend_hits = sum(
            1 for kw in _BACKEND_STACK_HINTS if kw in _project_text_blob(p, profile)
        )
        backend_hits = sum(
            1 for kw in _BACKEND_STACK_HINTS if kw in _project_text_blob(p, profile)
        )
        # 纯后端栈且与岗位无关才跳过；含 Agent 段落的项目仍可从岗位视角问
        if role_ids and score < 0.5 and not agent_in_proj:
            continue
        tech_n = len(p.get("tech_stack") or p.get("tech") or [])
        chain_n = 0
        for pc in project_chains or []:
            if str(pc.get("project") or "").strip() == name:
                chain_n = len(pc.get("chains") or [])
                break
        slots = 0
        if score >= 2.0:
            slots = 2 + (1 if len(desc) >= 80 else 0) + (1 if chain_n >= 3 else 0)
        elif score >= 1.0:
            slots = 1 + (1 if chain_n >= 2 or len(desc) >= 60 else 0)
        else:
            slots = 1 if chain_n >= 1 or len(desc) >= 40 or agent_in_proj else 0
        if agent_in_proj and score < 1.0:
            slots = min(max(slots, 1), 2)  # 混合项目：可问但配额少于纯 Agent 项目
        if tech_n >= 4 and score >= 1.0:
            slots += 1
        slots = min(slots, 3)
        if slots > 0:
            askable.append(
                {
                    "kind": "project",
                    "name": name,
                    "slots": slots,
                    "role_score": score,
                    "chain_count": chain_n,
                    "mixed_stack": agent_in_proj and backend_hits >= 1,
                }
            )

    for exp in _experience_items(profile)[:2]:
        name = str(
            exp.get("company") or exp.get("name") or exp.get("title") or ""
        ).strip()
        role_line = str(exp.get("role") or exp.get("position") or "").strip()
        desc = str(exp.get("desc") or exp.get("description") or exp.get("content") or "")
        label = name or role_line
        if not label:
            continue
        blob = json.dumps(exp, ensure_ascii=False).lower()
        score = 0.0
        if role_ids:
            roles_cfg = all_roles()
            for rid in role_ids:
                for kw in roles_cfg.get(rid, {}).get("keywords") or []:
                    if kw.lower() in blob:
                        score += 1.0
        if role_ids and score < 0.5:
            continue
        slots = 0
        if score >= 2.0 and len(desc) >= 50:
            slots = 2
        elif score >= 1.0 and len(desc) >= 30:
            slots = 1
        elif score >= 0.5 and len(desc) >= 80:
            slots = 1
        if slots > 0:
            askable.append(
                {
                    "kind": "internship",
                    "name": f"{label}（实习）" if name else f"{role_line}（实习）",
                    "slots": min(slots, 2),
                    "role_score": score,
                    "chain_count": 0,
                }
            )

    total_slots = sum(int(x.get("slots") or 0) for x in askable)
    return {
        "askable": askable,
        "max_project_questions": total_slots,
        "has_askable": total_slots > 0,
        "role_relevant_items": len(askable),
    }


def plan_project_bagu_split(
    budget: int,
    capacity: dict,
    *,
    project_clamp: tuple[int, int] = (0, 10),
) -> tuple[int, int]:
    """分题策略：岗位可问项目题先占坑，其余全部八股。"""
    budget = max(1, int(budget))
    lo, hi = project_clamp
    max_proj = int(capacity.get("max_project_questions") or 0)
    if max_proj <= 0:
        return 0, budget
    project_n = min(max_proj, hi, budget)
    if project_n < lo and budget >= lo:
        project_n = min(lo, max_proj, budget)
    if project_n >= budget:
        project_n = max(0, budget - 1)
    return project_n, max(1, budget - project_n) if project_n < budget else 0


def infer_company(text: str) -> str | None:
    """从文本（如面经标题）匹配企业 id，别名大小写不敏感。"""
    t = text.lower()
    for cfg in load_companies()["companies"]:
        if any(alias.lower() in t for alias in cfg["aliases"]):
            return cfg["id"]
    return None


def resolve_company_id(target_company: str) -> str | None:
    """把用户选择的企业名/别名/id 解析为知识库 company id。

    例：腾讯/tencent/TX → tencent；字节跳动/字节 → bytedance。
    """
    raw = (target_company or "").strip()
    if not raw:
        return None
    low = raw.lower()
    for cfg in load_companies()["companies"]:
        if raw == cfg["id"] or low == str(cfg["id"]).lower():
            return cfg["id"]
        if raw == cfg.get("name"):
            return cfg["id"]
        for alias in cfg.get("aliases") or []:
            if raw == alias or low == str(alias).lower():
                return cfg["id"]
    return infer_company(raw)


def company_display_name(company_id_or_name: str) -> str:
    """企业 id 或别名 → 展示名（腾讯）；找不到则原样返回。"""
    raw = (company_id_or_name or "").strip()
    if not raw:
        return ""
    cid = resolve_company_id(raw) or raw
    for cfg in load_companies()["companies"]:
        if cfg["id"] == cid:
            return str(cfg.get("name") or cid)
    return raw
