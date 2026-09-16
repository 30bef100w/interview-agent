"""题面语义召回：不读岗位/场景标签，只对 question+answer 做相似度。

两种后端：
- ngram：字 2/3-gram 余弦（本地、可复现，是词面相近而不是神经网络语义）
- embed：OpenAI 兼容 embeddings 接口，向量暴力 topK（评测里的「向量召回」）

评测用，不接入生产 retrieve()。
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

from app.services.knowledge_retrieval import load_questions

_TOKEN_RE = re.compile(r"[\W_]+", re.UNICODE)


def question_corpus_text(q: dict) -> str:
    answer = str(q.get("answer") or "")[:400]
    return f"{q.get('question') or ''} {answer}".strip()


def query_corpus_text(query: dict) -> str:
    parts = [
        str(query.get("query_text") or ""),
        " ".join(query.get("skills") or []),
        str(query.get("target_role") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def _ngrams(text: str) -> dict[str, int]:
    t = _TOKEN_RE.sub("", (text or "").lower())
    counts: dict[str, int] = {}
    if not t:
        return counts
    if len(t) == 1:
        return {t: 1}
    for n in (2, 3):
        if len(t) < n:
            continue
        for i in range(len(t) - n + 1):
            g = t[i : i + n]
            counts[g] = counts.get(g, 0) + 1
    return counts


def _cosine_sparse(a: dict[str, int], b: dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = 0.0
    for k, va in a.items():
        vb = b.get(k)
        if vb:
            dot += va * vb
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _cosine_dense(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@lru_cache(maxsize=1)
def _ngram_index(question_source: str) -> tuple[tuple[dict[str, int], ...], tuple[int, ...]]:
    """question_source 只用于区分 cache key（demo/full）。"""
    _ = question_source
    vecs: list[dict[str, int]] = []
    keep: list[int] = []
    for i, q in enumerate(load_questions()):
        text = question_corpus_text(q)
        if len(text) < 8:
            continue
        vecs.append(_ngrams(text))
        keep.append(i)
    return tuple(vecs), tuple(keep)


def retrieve_ngram(query: dict, *, top_n: int = 8, min_score: float = 0.02) -> list[dict]:
    questions = load_questions()
    qvec = _ngrams(query_corpus_text(query))
    scored: list[tuple[float, dict]] = []
    vecs, keep = _ngram_index(str(len(questions)))
    for vec, idx in zip(vecs, keep):
        s = _cosine_sparse(qvec, vec)
        if s < min_score:
            continue
        scored.append((s, questions[idx]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [q for _, q in scored[:top_n]]


def retrieve_embed(
    query: dict,
    *,
    top_n: int = 8,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
    min_score: float = 0.15,
) -> list[dict]:
    """OpenAI 兼容 embeddings + 内存暴力 topK。"""
    from openai import OpenAI

    from app.config import settings

    questions = load_questions()
    texts: list[str] = []
    keep: list[int] = []
    for i, q in enumerate(questions):
        text = question_corpus_text(q)
        if len(text) < 8:
            continue
        texts.append(text)
        keep.append(i)
    if not texts:
        return []

    client = OpenAI(
        api_key=api_key or settings.deepseek_api_key,
        base_url=base_url or settings.deepseek_base_url,
        timeout=120,
    )

    def _embed_batch(batch: list[str]) -> list[list[float]]:
        resp = client.embeddings.create(model=model, input=batch)
        ordered = sorted(resp.data, key=lambda d: d.index)
        return [list(d.embedding) for d in ordered]

    doc_vecs: list[list[float]] = []
    chunk = 64
    for start in range(0, len(texts), chunk):
        doc_vecs.extend(_embed_batch(texts[start : start + chunk]))
    qvec = _embed_batch([query_corpus_text(query)])[0]

    scored: list[tuple[float, dict]] = []
    for vec, idx in zip(doc_vecs, keep):
        s = _cosine_dense(qvec, vec)
        if s < min_score:
            continue
        scored.append((s, questions[idx]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [q for _, q in scored[:top_n]]


def apply_role_filter(hits: list[dict], roles: list[str] | None) -> list[dict]:
    if not roles:
        return hits
    allowed = set(roles)
    return [h for h in hits if allowed & set(h.get("roles") or [])]
