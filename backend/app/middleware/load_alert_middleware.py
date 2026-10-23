"""流量过载检测：RPM 超阈值时飞书告警（冷却去重）。"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.services.feishu_notify import send_throttled_ops_alert

logger = logging.getLogger("app.load_alert")

_lock = threading.Lock()
_timestamps: deque[float] = deque()
_alert_inflight = False
_last_attempt = float("-inf")


def _record_request(now: float) -> int:
    with _lock:
        while _timestamps and now - _timestamps[0] >= 60:
            _timestamps.popleft()
        _timestamps.append(now)
        return len(_timestamps)


def _maybe_alert_overload(rpm: int) -> None:
    global _alert_inflight, _last_attempt
    threshold = int(settings.alert_rpm_threshold or 0)
    if threshold <= 0 or rpm < threshold:
        return
    with _lock:
        now = time.monotonic()
        if _alert_inflight or now - _last_attempt < max(60, settings.alert_cooldown_seconds):
            return
        _alert_inflight = True
        _last_attempt = now  # Failed delivery must also back off.

    def deliver() -> None:
        global _alert_inflight
        try:
            send_throttled_ops_alert(
                "traffic_overload", "流量过载", rpm=rpm, threshold=threshold,
                window="最近 60 秒", hint="请检查是否被刷量，或考虑扩容/限流",
            )
        except Exception:
            logger.exception("overload alert failed")
        finally:
            with _lock:
                _alert_inflight = False
    try:
        threading.Thread(target=deliver, daemon=True, name="overload-alert").start()
    except RuntimeError:
        with _lock:
            _alert_inflight = False
        logger.exception("overload alert worker could not start")


class LoadAlertMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rpm = _record_request(time.time())
        if request.url.path != "/api/health":
            _maybe_alert_overload(rpm)
        return await call_next(request)
