"""Graph 节点 trace：耗时 + 结果写入 session 级 JSONL（参考 Gua GraphTraceAspect）。"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from app.observability.metrics import metrics_registry
from app.observability.trace_context import get_trace_id

logger = logging.getLogger("app.trace")
_TRACE_DIR = Path(__file__).resolve().parents[2] / "logs" / "engine_trace"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def append_session_trace(session_id: int, row: dict) -> None:
    if not session_id:
        return
    _TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = _TRACE_DIR / f"{session_id}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_session_trace(session_id: int, limit: int = 200) -> list[dict]:
    path = _TRACE_DIR / f"{session_id}.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


@contextmanager
def trace_node(
    node: str,
    *,
    session_id: int | None = None,
    **extra,
) -> Iterator[None]:
    """记录节点开始/结束、耗时、异常；写入 metrics + engine_trace JSONL。"""
    t0 = time.perf_counter()
    err: str | None = None
    try:
        yield
    except Exception as exc:
        err = type(exc).__name__
        raise
    finally:
        ms = (time.perf_counter() - t0) * 1000
        metrics_registry.record_node(node, ms, error=err)
        row = {
            "ts": _now(),
            "trace_id": get_trace_id(),
            "session_id": session_id,
            "node": node,
            "duration_ms": round(ms, 1),
            "outcome": "error" if err else "ok",
            **({"error": err} if err else {}),
            **{k: v for k, v in extra.items() if v is not None},
        }
        if session_id:
            append_session_trace(session_id, row)
        logger.info(
            "[TRACE] node=%s session=%s duration=%.0fms outcome=%s",
            node,
            session_id,
            ms,
            row["outcome"],
        )
