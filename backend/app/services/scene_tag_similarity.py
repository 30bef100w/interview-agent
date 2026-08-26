"""简历 scene_tags ↔ 题库 business_scene/tech_scene 相似度（非精确映射）。

算法：预置场景词表扩展 + 加权 Jaccard + 标签名字符 2-gram 重叠。
- 完全同名标签 → 1.0
- 共享 keywords（project_scenes.json）→ Jaccard 映射到 [0.45, 1.0]
- 无词表命中时 → 标签名 2-gram 余弦 × 0.45（兜底近义/子串）
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_SCENES_PATH = Path(__file__).resolve().parents[2] / "data" / "project_scenes.json"

# B 路召回：低于此相似度不计场景加分（避免弱相关噪音）
SCENE_SIM_MIN = 0.28


def _char_bigrams(text: str) -> dict[str, int]:
    norm = re.sub(r"\s+", "", (text or "").lower())
    if len(norm) < 2:
        return {norm: 1} if norm else {}
    grams: dict[str, int] = {}
    for i in range(len(norm) - 1):
        g = norm[i : i + 2]
        grams[g] = grams.get(g, 0) + 1
    return grams


def _cosine_from_counters(a: dict[str, int], b: dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in a.keys() & b.keys())
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


@lru_cache(maxsize=1)
def _canonical_tag_keywords() -> dict[str, set[str]]:
    """canonical 场景名 → 扩展关键词集合（含自身与 id）。"""
    out: dict[str, set[str]] = {}
    try:
        raw = json.loads(_SCENES_PATH.read_text(encoding="utf-8"))
    except OSError:
        return out
    for group in ("business_scenes", "tech_scenes"):
        for item in raw.get(group, []):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            bag: set[str] = {name.lower(), str(item.get("id") or "").lower()}
            for kw in item.get("keywords") or []:
                k = str(kw).strip().lower()
                if k:
                    bag.add(k)
            out[name] = bag
    return out


def _expand_tag(tag: str) -> set[str]:
    tag = (tag or "").strip()
    if not tag:
        return set()
    canon = _canonical_tag_keywords()
    bag: set[str] = {tag.lower()}
    if tag in canon:
        bag |= canon[tag]
    for part in re.split(r"[/、|]+", tag):
        p = part.strip()
        if len(p) < 2:
            continue
        bag.add(p.lower())
        if p in canon:
            bag |= canon[p]
    return bag


def tag_pair_similarity(a: str, b: str) -> float:
    """两枚场景标签的相似度 [0, 1]。"""
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    bag_a = _expand_tag(a)
    bag_b = _expand_tag(b)
    best = 0.0
    if bag_a and bag_b:
        inter = bag_a & bag_b
        if inter:
            union = bag_a | bag_b
            best = max(best, 0.45 + 0.55 * (len(inter) / len(union)))
    # 标签名片段（中英文词元）重叠：如 AI 应用 ↔ AI/RAG/Agent
    tokens_a = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}", a.lower()))
    tokens_b = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}", b.lower()))
    if tokens_a and tokens_b:
        inter_t = tokens_a & tokens_b
        if inter_t:
            union_t = tokens_a | tokens_b
            best = max(best, 0.38 + 0.42 * (len(inter_t) / len(union_t)))
    char_sim = _cosine_from_counters(_char_bigrams(a), _char_bigrams(b)) * 0.45
    return max(best, char_sim)


def scene_tags_similarity(resume_tags: list[str], question_tags: list[str]) -> float:
    """简历侧标签集合 vs 题目侧标签集合：对每个简历标签取最佳匹配后平均。"""
    r_tags = [str(t).strip() for t in (resume_tags or []) if str(t).strip()]
    q_tags = [str(t).strip() for t in (question_tags or []) if str(t).strip()]
    if not r_tags or not q_tags:
        return 0.0
    per_resume = [max(tag_pair_similarity(rt, qt) for qt in q_tags) for rt in r_tags]
    return sum(per_resume) / len(per_resume)


def scene_score_bonus(
    resume_tags: list[str],
    question_tags: list[str],
    *,
    has_roles: bool,
) -> float:
    """供 knowledge_retrieval 使用的场景加分（0 表示无有效相似）。"""
    sim = scene_tags_similarity(resume_tags, question_tags)
    if sim < SCENE_SIM_MIN:
        return 0.0
    base = 45.0 if has_roles else 80.0
    exact_n = len(set(resume_tags or []) & set(question_tags or []))
    return sim * base + exact_n * 8.0
