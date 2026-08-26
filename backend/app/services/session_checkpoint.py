"""面试会话 checkpoint：弱网重连时快速恢复最近快照（文件落盘，无需 Redis）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_CHECKPOINT_DIR = Path(__file__).resolve().parents[2] / "logs" / "session_checkpoint"


def _path(session_id: int) -> Path:
    _CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return _CHECKPOINT_DIR / f"{session_id}.json"


def save_checkpoint(session_id: int, payload: dict) -> int:
    """写入会话快照，返回递增 seq。"""
    prev = load_checkpoint(session_id)
    seq = int((prev or {}).get("seq", 0)) + 1
    data = {
        **payload,
        "seq": seq,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    _path(session_id).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return seq


def load_checkpoint(session_id: int) -> dict | None:
    p = _path(session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
