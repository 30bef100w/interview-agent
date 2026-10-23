"""面试 WebSocket：快照恢复 + 流式答题（替代 SSE 的弱网友好通道）。"""
from __future__ import annotations

import asyncio
import json
import logging
import threading

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.deps import authenticate_token
from app.db import SessionLocal
from app.models import InterviewSession
from app.services.client_errors import public_error_message
from app.services.session_checkpoint import load_checkpoint
from app.schemas.api import AnswerRequest

from app.api.interview import (
    _build_session_view,
    _load_state,
    _submit_answer_command,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["interview-ws"])


async def _send_json(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _stream_answer(ws: WebSocket, session_id: int, token: str, payload: AnswerRequest) -> None:
    loop = asyncio.get_running_loop()
    q: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

    def producer() -> None:
        from app.observability.trace_context import new_trace_id, set_session_id, set_trace_id

        set_session_id(session_id)
        set_trace_id(new_trace_id())
        thread_db = SessionLocal()
        try:
            user = authenticate_token(thread_db, token)

            def on_token(tok: str) -> None:
                loop.call_soon_threadsafe(q.put_nowait, ("token", tok))

            out = _submit_answer_command(thread_db, user, session_id, payload, on_token)
            loop.call_soon_threadsafe(q.put_nowait, ("done", out))
        except Exception as e:  # noqa: BLE001
            try:
                thread_db.rollback()
            except Exception:  # noqa: BLE001
                pass
            logger.exception("interview ws answer failed session_id=%s", session_id)
            loop.call_soon_threadsafe(q.put_nowait, ("error", {
                "message": public_error_message(e), "status": getattr(e, "status_code", 500),
            }))
        finally:
            thread_db.close()

    threading.Thread(target=producer, daemon=True).start()

    while True:
        kind, data = await q.get()
        if kind == "token":
            await _send_json(ws, {"type": "token", "data": data})
        elif kind == "done":
            await _send_json(ws, {"type": "done", "data": data})
            return
        elif kind == "error":
            await _send_json(ws, {"type": "error", **data})
            if data["status"] in {401, 403}:
                await ws.close(code=4401 if data["status"] == 401 else 4403)
            return


def _snapshot(session_id: int, token: str) -> dict:
    # No ORM session/transaction survives the return into an await/receive loop.
    with SessionLocal() as db:
        user = authenticate_token(db, token)
        sess = db.get(InterviewSession, session_id)
        if sess is None or sess.user_id != user.id:
            raise HTTPException(404, "会话不存在")
        view = _build_session_view(sess, _load_state(sess))
    try:
        cp = load_checkpoint(session_id)
    except Exception:
        logger.exception("checkpoint load failed session_id=%s", session_id)
        cp = None
    return {"type": "snapshot", "data": view, "checkpoint_seq": int((cp or {}).get("seq", 0))}


def _check_token(token: str) -> None:
    with SessionLocal() as db:
        authenticate_token(db, token)


@router.websocket("/ws/interview/{session_id}")
async def interview_websocket(
    websocket: WebSocket,
    session_id: int,
    token: str = Query(default=""),
) -> None:
    await websocket.accept()
    try:
        await _send_json(websocket, await asyncio.to_thread(_snapshot, session_id, token))

        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=60)
            except asyncio.TimeoutError:
                await asyncio.to_thread(_check_token, token)
                continue
            await asyncio.to_thread(_check_token, token)
            if len(raw.encode("utf-8")) > 16_384:
                await _send_json(websocket, {"type": "error", "message": "消息过长"})
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_json(websocket, {"type": "error", "message": "无效 JSON"})
                continue

            if not isinstance(msg, dict):
                await _send_json(websocket, {"type": "error", "message": "消息必须是 JSON 对象"})
                continue
            mtype = str(msg.get("type", "")).lower()
            if mtype in {"ping", "heartbeat"}:
                await _send_json(websocket, {"type": "pong"})
            elif mtype == "resync":
                await _send_json(websocket, await asyncio.to_thread(_snapshot, session_id, token))
            elif mtype == "answer":
                try:
                    payload = AnswerRequest.model_validate({k: v for k, v in msg.items() if k != "type"})
                    if not payload.text.strip():
                        raise ValueError("empty answer")
                except (ValidationError, ValueError):
                    await _send_json(websocket, {"type": "error", "message": "回答须为 1～2000 字的非空文本，提交参数须有效"})
                    continue
                await _stream_answer(websocket, session_id, token, payload)
            else:
                await _send_json(websocket, {"type": "error", "message": f"未知消息类型: {mtype}"})
    except WebSocketDisconnect:
        logger.info("interview ws disconnected session_id=%s", session_id)
    except HTTPException as exc:
        await _send_json(websocket, {"type": "error", "message": str(exc.detail), "status": exc.status_code})
        await websocket.close(code={401: 4401, 403: 4403, 404: 4404}.get(exc.status_code, 4400))
    except Exception as e:  # noqa: BLE001
        logger.exception("interview ws error session_id=%s", session_id)
        try:
            await _send_json(websocket, {"type": "error", "message": public_error_message(e)})
        except Exception:  # noqa: BLE001
            pass
