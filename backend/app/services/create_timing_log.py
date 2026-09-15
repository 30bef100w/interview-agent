"""创建会话逐步追踪：每走一步写时间戳，全部落在 logs/create_trace/{session_id}.json。

参见 session_guard_log：全生命周期兜底/门禁事件写入 logs/session_guard/{session_id}.jsonl。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from app.observability.safe_files import write_text_soft

_TRACE_DIR = Path(__file__).resolve().parents[2] / "logs" / "create_trace"
_CLOCKS: dict[int, float] = {}


def _path(session_id: int) -> Path:
    return _TRACE_DIR / f"{session_id}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def begin(session_id: int, **meta) -> None:
    _CLOCKS[session_id] = time.perf_counter()
    payload = {
        "session_id": session_id,
        "started_at": _now(),
        "meta": meta,
        "steps": [
            {
                "step": "begin",
                "ts": _now(),
                "elapsed_s": 0.0,
                **meta,
            }
        ],
    }
    write_text_soft(_path(session_id), json.dumps(payload, ensure_ascii=False, indent=2))


def step(session_id: int, name: str, **extra) -> None:
    if session_id not in _CLOCKS:
        begin(session_id)
    path = _path(session_id)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    elapsed = round(time.perf_counter() - _CLOCKS[session_id], 2)
    prev = data["steps"][-1]["elapsed_s"] if data.get("steps") else 0.0
    data.setdefault("steps", []).append(
        {
            "step": name,
            "ts": _now(),
            "elapsed_s": elapsed,
            "step_s": round(elapsed - prev, 2),
            **extra,
        }
    )
    write_text_soft(path, json.dumps(data, ensure_ascii=False, indent=2))


def finish(session_id: int, **extra) -> None:
    step(session_id, "finish", **extra)
    path = _path(session_id)
    started = _CLOCKS.pop(session_id, None)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    data["finished_at"] = _now()
    if started is not None:
        data["total_s"] = round(time.perf_counter() - started, 2)
    write_text_soft(path, json.dumps(data, ensure_ascii=False, indent=2))
