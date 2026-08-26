"""请求级 trace_id（参考 Gua TraceContext + MDC 思路，Python contextvars 实现）。"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_session_id: ContextVar[int | None] = ContextVar("session_id", default=None)


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def set_trace_id(trace_id: str | None) -> None:
    _trace_id.set(trace_id)


def get_trace_id() -> str | None:
    return _trace_id.get()


def set_session_id(session_id: int | None) -> None:
    _session_id.set(session_id)


def get_session_id() -> int | None:
    return _session_id.get()
