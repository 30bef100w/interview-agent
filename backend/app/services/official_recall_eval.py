"""正式召回评测：全库规则金标 + Precision/Recall/MRR。

金标与两路排序器独立：不读标签分、也不读 n-gram 分。
相关 = 岗位有交集（题无 roles 则不因岗位淘汰）且题干+答案命中 positives，且不含 negatives。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services import knowledge_retrieval as kr
from app.services.job_roles import resolve_company_id, resolve_target_roles

OFFICIAL_PATH = Path(__file__).resolve().parents[2] / "data" / "eval" / "official_queries.json"


def load_official(path: Path | None = None) -> dict:
    with open(path or OFFICIAL_PATH, encoding="utf-8") as f:
        return json.load(f)


def question_blob(q: dict) -> str:
    return f"{q.get('question') or ''} {q.get('answer') or ''}".lower()


def is_relevant(q: dict, spec: dict) -> bool:
    text = question_blob(q)
    for neg in spec.get("negatives") or []:
        if neg.lower() in text:
            return False
    need_roles = set(spec.get("roles") or [])
    q_roles = set(q.get("roles") or [])
    if need_roles and q_roles and not (need_roles & q_roles):
        return False
    positives = [p.lower() for p in (spec.get("positives") or [])]
    if not positives:
        return False
    hits = sum(1 for p in positives if p in text)
    return hits >= int(spec.get("min_positives") or 1)


def doc_id(q: dict) -> str:
    return kr._question_norm(q)


def build_qrels(questions: list[dict], queries: list[dict]) -> dict[str, set[str]]:
    blobs: list[tuple[str, str, set[str]]] = []
    for q in questions:
        key = doc_id(q)
        if not key:
            continue
        blobs.append((key, question_blob(q), set(q.get("roles") or [])))

    qrels: dict[str, set[str]] = {}
    for spec in queries:
        need_roles = set(spec.get("roles") or [])
        positives = [p.lower() for p in (spec.get("positives") or [])]
        negatives = [n.lower() for n in (spec.get("negatives") or [])]
        need = int(spec.get("min_positives") or 1)
        rel: set[str] = set()
        for key, text, q_roles in blobs:
            if any(n in text for n in negatives):
                continue
            if need_roles and q_roles and not (need_roles & q_roles):
                continue
            if positives and sum(1 for p in positives if p in text) >= need:
                rel.add(key)
        qrels[spec["id"]] = rel
    return qrels


def retrieve_tag_score(query: dict, top_n: int) -> list[dict]:
    """标签打分 Top-N（无多样性截断），对应线上 A/B 的排序函数。

    线上会把 JD / 练习焦点抽成 recall_boost_terms 写进题干打分。
    评测把 query_text 当作练习焦点，否则等于关掉了生产加权。
    """
    from app.services.recall_boost import build_recall_boost_terms

    roles = resolve_target_roles(query.get("target_role") or "")
    company = resolve_company_id(query.get("target_company") or "")
    skills = list(query.get("skills") or [])
    scenes = list(query.get("scenes") or [])
    boost = list(query.get("recall_boost_terms") or []) or build_recall_boost_terms(
        query.get("query_text") or "",
        query.get("practice_focus") or "",
        query.get("job_description") or "",
    )
    a = kr.search_questions(
        roles=roles or None,
        company=company,
        skills=skills[:6],
        scenes=None,
        top_n=top_n,
        min_score=10,
        recall_boost_terms=boost,
    )
    b: list[dict] = []
    if scenes:
        b = kr.search_questions(
            roles=roles or None,
            company=company,
            skills=skills,
            scenes=scenes,
            category="project",
            top_n=max(4, top_n // 2),
            min_score=10,
            recall_boost_terms=boost,
        )
    seen: set[str] = set()
    merged: list[dict] = []
    for h in a + b:
        key = doc_id(h)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(h)
        if len(merged) >= top_n:
            break
    return merged


def ranked_ids(hits: list[dict]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for h in hits:
        key = doc_id(h)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def metrics_at_k(ranked: list[str], rel: set[str], k: int) -> dict:
    cut = ranked[:k]
    n = len(cut)
    if not rel:
        return {"k": k, "n": n, "|Rel|": 0, "hits": 0, "P": None, "R": None, "Success": None, "RR": None}
    hits = sum(1 for x in cut if x in rel)
    rr = 0.0
    for i, x in enumerate(ranked, 1):
        if x in rel:
            rr = 1.0 / i
            break
    return {
        "k": k,
        "n": n,
        "|Rel|": len(rel),
        "hits": hits,
        "P": hits / n if n else 0.0,
        "R": hits / len(rel),
        "Success": 1.0 if hits else 0.0,
        "RR": rr,
    }


def mean_field(rows: list[dict], field: str) -> float | None:
    nums = [r[field] for r in rows if r.get(field) is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)
