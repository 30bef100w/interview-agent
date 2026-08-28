"""流量过载检测：RPM 超阈值时飞书告警（冷却去重）。"""
from __future__ import annotations

import logging
import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.services.feishu_notify import send_throttled_ops_alert

logger = logging.getLogger("app.load_alert")

_lock = threading.Lock()
_timestamps: list[float] = []


def _record_request(now: float) -> int:
    global _timestamps
    with _lock:
        _timestamps = [t for t in _timestamps if now - t < 60.0]
        _timestamps.append(now)
        return len(_timestamps)


def _maybe_alert_overload(rpm: int) -> None:
    threshold = int(settings.alert_rpm_threshold or 0)
    if threshold <= 0 or rpm < threshold:
        return
    send_throttled_ops_alert(
        "traffic_overload",
        "流量过载",
        rpm=rpm,
        threshold=threshold,
        window="最近 60 秒",
        hint="请检查是否被刷量，或考虑扩容/限流",
    )


class LoadAlertMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rpm = _record_request(time.time())
        if request.url.path != "/api/health":
            _maybe_alert_overload(rpm)
        return await call_next(request)
