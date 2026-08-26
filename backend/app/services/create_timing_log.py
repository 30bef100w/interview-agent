"""创建会话逐步追踪：每走一步写时间戳，全部落在 logs/create_trace/{session_id}.json。

参见 session_guard_log：全生命周期兜底/门禁事件写入 logs/session_guard/{session_id}.jsonl。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

_TRACE_DIR = Path(__file__).resolve().parents[2] / "logs" / "create_trace"
_CLOCKS: dict[int, float] = {}


def _path(session_id: int) -> Path:
    return _TRACE_DIR / f"{session_id}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def begin(session_id: int, **meta) -> None:
    _TRACE_DIR.mkdir(parents=True, exist_ok=True)
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
    _path(session_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def step(session_id: int, name: str, **extra) -> None:
    if session_id not in _CLOCKS:
        begin(session_id)
    data = json.loads(_path(session_id).read_text(encoding="utf-8"))
    elapsed = round(time.perf_counter() - _CLOCKS[session_id], 2)
    prev = data["steps"][-1]["elapsed_s"] if data["steps"] else 0.0
    data["steps"].append(
        {
            "step": name,
            "ts": _now(),
            "elapsed_s": elapsed,
            "step_s": round(elapsed - prev, 2),
            **extra,
        }
    )
    _path(session_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def finish(session_id: int, **extra) -> None:
    step(session_id, "finish", **extra)
    if session_id in _CLOCKS:
        data = json.loads(_path(session_id).read_text(encoding="utf-8"))
        data["finished_at"] = _now()
        data["total_s"] = round(time.perf_counter() - _CLOCKS.pop(session_id), 2)
        _path(session_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
