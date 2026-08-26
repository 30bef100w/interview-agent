"""会话级兜底 / 门禁事件日志（append-only JSONL）。

与 create_timing_log 互补：
- logs/create_trace/{session_id}.json   — 创建阶段分步耗时
- logs/session_guard/{session_id}.jsonl — 全生命周期兜底与硬门禁事件
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

_GUARD_DIR = Path(__file__).resolve().parents[2] / "logs" / "session_guard"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_guard(session_id: int | None, event: str, **detail) -> None:
    """记录一条兜底/门禁事件；session_id 缺失时写入 session_guard/_anonymous.jsonl。"""
    if not event:
        return
    _GUARD_DIR.mkdir(parents=True, exist_ok=True)
    sid = int(session_id) if session_id else 0
    path = _GUARD_DIR / (f"{sid}.jsonl" if sid else "_anonymous.jsonl")
    row = {
        "ts": _now(),
        "session_id": sid or None,
        "event": event,
        **{k: v for k, v in detail.items() if v is not None},
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
