"""飞书告警去重：同一 alert_key 在冷却期内只发一次。"""
from __future__ import annotations

import time
from typing import Any

from app.config import settings
from app.services.feishu_notify import _load_state, _save_state

_STATE_KEY = "alert_throttle"


def _bucket() -> dict[str, Any]:
    state = _load_state()
    raw = state.get(_STATE_KEY)
    return raw if isinstance(raw, dict) else {}


def _write_bucket(bucket: dict[str, Any]) -> None:
    state = _load_state()
    state[_STATE_KEY] = bucket
    _save_state(state)


def should_send_alert(alert_key: str, cooldown_seconds: int | None = None) -> bool:
    key = (alert_key or "").strip()
    if not key:
        return False
    cd = max(60, int(cooldown_seconds or settings.alert_cooldown_seconds or 600))
    bucket = _bucket()
    last = float(bucket.get(key) or 0)
    return (time.time() - last) >= cd


def mark_alert_sent(alert_key: str) -> None:
    key = (alert_key or "").strip()
    if not key:
        return
    bucket = _bucket()
    bucket[key] = time.time()
    _write_bucket(bucket)
