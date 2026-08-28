"""面试会话 checkpoint：Redis 优先，文件落盘兜底（弱网重连快照）。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

_CHECKPOINT_DIR = Path(__file__).resolve().parents[2] / "logs" / "session_checkpoint"
_REDIS_TTL_SEC = 7 * 24 * 3600


def _file_path(session_id: int) -> Path:
    _CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return _CHECKPOINT_DIR / f"{session_id}.json"


def _redis_keys(session_id: int) -> tuple[str, str]:
    return f"checkpoint:{session_id}:seq", f"checkpoint:{session_id}:data"


def save_checkpoint(session_id: int, payload: dict) -> int:
    """写入会话快照，返回递增 seq。"""
    data_base = {
        **payload,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    r = get_redis()
    if r is not None:
        try:
            seq_key, data_key = _redis_keys(session_id)
            seq = int(r.incr(seq_key))
            r.expire(seq_key, _REDIS_TTL_SEC)
            data = {**data_base, "seq": seq}
            r.setex(data_key, _REDIS_TTL_SEC, json.dumps(data, ensure_ascii=False))
            return seq
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis checkpoint save failed session=%s: %s", session_id, exc)

    prev = _load_file(session_id)
    seq = int((prev or {}).get("seq", 0)) + 1
    data = {**data_base, "seq": seq}
    _file_path(session_id).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return seq


def load_checkpoint(session_id: int) -> dict | None:
    r = get_redis()
    if r is not None:
        try:
            _, data_key = _redis_keys(session_id)
            raw = r.get(data_key)
            if raw:
                return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis checkpoint load failed session=%s: %s", session_id, exc)
    return _load_file(session_id)


def _load_file(session_id: int) -> dict | None:
    p = _file_path(session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
