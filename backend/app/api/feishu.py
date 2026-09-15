"""飞书事件订阅 Webhook（与网页共用 backend）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.services.feishu_dispatch import process_inbound_async
from app.services.feishu_events import FeishuEventError, flatten_message_event, parse_callback

logger = logging.getLogger("app.feishu_webhook")

router = APIRouter(prefix="/api/feishu", tags=["feishu"])


@router.post("/event")
async def feishu_event(request: Request):
    raw = await request.body()
    timestamp = request.headers.get("x-lark-request-timestamp") or ""
    nonce = request.headers.get("x-lark-request-nonce") or ""
    signature = request.headers.get("x-lark-signature") or ""
    try:
        payload = parse_callback(
            raw, timestamp=timestamp, nonce=nonce, signature=signature
        )
    except FeishuEventError as exc:
        logger.warning("feishu webhook reject: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if payload.get("_url_verification"):
        return {"challenge": payload["challenge"]}
    event = flatten_message_event(payload)
    if event is None:
        return JSONResponse({"code": 0})
    logger.info(
        "feishu webhook message id=%s chat=%s sender=%s",
        event.get("message_id"),
        event.get("chat_id"),
        event.get("sender_id"),
    )
    process_inbound_async(event)
    return JSONResponse({"code": 0})
