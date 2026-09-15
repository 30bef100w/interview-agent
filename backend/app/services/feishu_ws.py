"""在网页 backend 进程内用飞书官方长连接收私聊（无需单独 bot 容器）。"""
from __future__ import annotations

import json
import logging
import os
import threading

from app.config import settings
from app.services.feishu_dispatch import process_inbound_async

logger = logging.getLogger("app.feishu_ws")

_started = False
_lock = threading.Lock()


def ws_should_start() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if not settings.is_production:
        return False
    if not bool(settings.feishu_ws_enabled):
        return False
    return bool((settings.feishu_app_id or "").strip() and (settings.feishu_app_secret or "").strip())


def payload_from_ws_event(data: object) -> dict:
    if isinstance(data, dict):
        return data
    try:
        import lark_oapi as lark

        raw = lark.JSON.marshal(data)
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception:
        logger.exception("feishu ws marshal failed")
    return {}


def _on_message(data) -> None:
    payload = payload_from_ws_event(data)
    if not payload:
        return
    process_inbound_async(payload)


def start_feishu_ws() -> bool:
    """生产启动一次。失败只打日志，不挡住网页。"""
    global _started
    if not ws_should_start():
        return False
    with _lock:
        if _started:
            return True
        try:
            import lark_oapi as lark
        except ImportError:
            logger.warning("lark-oapi not installed, skip feishu ws")
            return False

        encrypt = (settings.feishu_encrypt_key or "").strip()
        token = (settings.feishu_verification_token or "").strip()
        handler = (
            lark.EventDispatcherHandler.builder(encrypt, token)
            .register_p2_im_message_receive_v1(_on_message)
            .build()
        )
        client = lark.ws.Client(
            settings.feishu_app_id.strip(),
            settings.feishu_app_secret.strip(),
            event_handler=handler,
            log_level=lark.LogLevel.INFO,
        )

        def _run() -> None:
            logger.info("feishu ws listener starting")
            try:
                client.start()
            except Exception:
                logger.exception("feishu ws listener stopped")

        threading.Thread(target=_run, daemon=True, name="feishu-ws").start()
        _started = True
        return True
