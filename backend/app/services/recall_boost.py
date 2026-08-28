"""JD / 练习焦点 → 检索加权词提取（仅用于题库召回打分，不进规划 Prompt）。"""
from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar

_BOOST: ContextVar[list[str]] = ContextVar("recall_boost_terms", default=[])

_CN_STOP = frozenset(
    "的 了 与 及 和 或 等 进行 负责 熟悉 了解 掌握 具备 有 对 为 在 中 上 下 将 能 可 你 我们 公司 岗位 工作 相关 以及 优先 最好 至少".split()
)

_LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_+#.-]{1,}")


def build_recall_boost_terms(*texts: str, max_terms: int = 28) -> list[str]:
    """合并 JD 与练习焦点，提取检索加权关键词。"""
    blob = "\n".join((t or "").strip() for t in texts if (t or "").strip())
    if not blob:
        return []

    from app.services.knowledge_retrieval import _tech_words

    tech = _tech_words()
    low = blob.lower()
    found: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        t = (term or "").strip()
        if not t or len(t) < 2:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(t)

    for w in sorted(tech, key=len, reverse=True):
        if len(w) >= 2 and w in low:
            _add(w)

    for m in _LATIN_TOKEN.finditer(blob):
        _add(m.group(0))

    for seg in re.split(r"[\s,，、;；/|]+", blob):
        seg = seg.strip()
        if not seg or len(seg) < 2:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]{2,12}", seg) and seg not in _CN_STOP:
            _add(seg)

    for m in re.finditer(r"[\u4e00-\u9fff]{2,8}", blob):
        phrase = m.group(0)
        if phrase in _CN_STOP:
            continue
        if any(w in phrase for w in tech if len(w) >= 2):
            _add(phrase)

    return found[:max_terms]


def active_recall_boost_terms() -> list[str]:
    return list(_BOOST.get() or [])


@contextmanager
def recall_boost_context(terms: list[str]):
    token = _BOOST.set(list(terms or []))
    try:
        yield
    finally:
        _BOOST.reset(token)
