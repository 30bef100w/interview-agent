"""飞书入站处理：CLI 长连接与 HTTP Webhook 共用。"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from app.config import settings
from app.services.feishu_channel import handle_inbound, parse_bind_map
from app.services.feishu_cli import send_markdown
from app.services.feishu_interview_runtime import FeishuInterviewRuntime

logger = logging.getLogger("app.feishu_dispatch")

_SEEN_MAX = 512
_seen: OrderedDict[str, None] = OrderedDict()
_seen_lock = threading.Lock()


def already_seen(key: str) -> bool:
    if not key:
        return False
    with _seen_lock:
        if key in _seen:
            return True
        _seen[key] = None
        if len(_seen) > _SEEN_MAX:
            _seen.popitem(last=False)
        return False


def process_inbound(event: dict) -> None:
    if event.get("header") or event.get("event"):
        from app.services.feishu_events import flatten_message_event

        flat = flatten_message_event(event)
        if flat is None:
            return
        event = flat
    chat_type = str(event.get("chat_type") or "")
    if chat_type and chat_type != "p2p":
        return
    sender_type = str(event.get("sender_type") or "user")
    if sender_type and sender_type != "user":
        return
    key = str(event.get("message_id") or event.get("event_id") or "")
    if already_seen(key):
        logger.info("skip duplicate feishu message %s", key)
        return
    chat_id = str(event.get("chat_id") or "")
    if not chat_id:
        return

    runtime = FeishuInterviewRuntime(bind_map=parse_bind_map(settings.feishu_bind_users))

    def emit(text: str) -> None:
        try:
            send_markdown(chat_id, text)
        except Exception:
            logger.exception("feishu emit failed")

    try:
        replies = handle_inbound(event, runtime=runtime, emit=emit)
    except Exception:
        logger.exception("feishu handle failed")
        replies = ["这一轮处理出错了，请稍后再试，或改用网页。"]
    for text in replies:
        try:
            send_markdown(chat_id, text)
        except Exception:
            logger.exception("feishu reply failed")


def process_inbound_async(event: dict) -> None:
    threading.Thread(
        target=process_inbound,
        args=(event,),
        daemon=True,
        name="feishu-event",
    ).start()
