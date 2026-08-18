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
