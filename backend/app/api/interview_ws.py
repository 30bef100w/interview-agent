"""面试 WebSocket：快照恢复 + 流式答题（替代 SSE 的弱网友好通道）。"""
from __future__ import annotations

import asyncio
import json
import logging
import threading

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.db import SessionLocal
from app.models import InterviewSession, User
from app.services.auth_service import decode_token
from app.services.interviewer_engine import InterviewEngine
from app.services.llm.client import StreamingLlm
from app.services.session_checkpoint import load_checkpoint, save_checkpoint

from app.api.interview import (
    _advance,
    _build_session_view,
    _engine_for,
    _load_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["interview-ws"])


def _auth_user_id(token: str) -> int | None:
    if not token.strip():
        return None
    return decode_token(token.strip())


async def _send_json(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _stream_answer(ws: WebSocket, session_id: int, user_id: int, text: str) -> None:
    loop = asyncio.get_running_loop()
    q: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

    def producer() -> None:
        thread_db = SessionLocal()
        try:
            sess = thread_db.get(InterviewSession, session_id)
            user = thread_db.get(User, user_id)
            if sess is None or user is None or sess.user_id != user_id:
                loop.call_soon_threadsafe(q.put_nowait, ("error", "会话不存在"))
                return
            if sess.status != "active":
                loop.call_soon_threadsafe(q.put_nowait, ("error", "面试已结束"))
                return

            def on_token(tok: str) -> None:
                loop.call_soon_threadsafe(q.put_nowait, ("token", tok))

            engine = _engine_for(thread_db, user, session_id)
            stream_engine = InterviewEngine(StreamingLlm(engine.llm, on_token))
            out = _advance(sess, thread_db, text, stream_engine)
            state = _load_state(sess)
            view = _build_session_view(sess, state)
            seq = save_checkpoint(session_id, view)
            out["_checkpoint_seq"] = seq
            loop.call_soon_threadsafe(q.put_nowait, ("done", out))
        except Exception as e:  # noqa: BLE001
            try:
                thread_db.rollback()
            except Exception:  # noqa: BLE001
                pass
            loop.call_soon_threadsafe(q.put_nowait, ("error", str(e)))
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
            await _send_json(ws, {"type": "error", "message": str(data)})
            return


@router.websocket("/ws/interview/{session_id}")
async def interview_websocket(
    websocket: WebSocket,
    session_id: int,
    token: str = Query(default=""),
) -> None:
    await websocket.accept()
    user_id = _auth_user_id(token)
    if user_id is None:
        await _send_json(websocket, {"type": "error", "message": "未登录或 token 无效"})
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        sess = db.get(InterviewSession, session_id)
        if sess is None or sess.user_id != user_id:
            await _send_json(websocket, {"type": "error", "message": "会话不存在"})
            await websocket.close(code=4404)
            return

        state = _load_state(sess)
        view = _build_session_view(sess, state)
        cp = load_checkpoint(session_id)
        await _send_json(
            websocket,
            {
                "type": "snapshot",
                "data": view,
                "checkpoint_seq": int((cp or {}).get("seq", 0)),
            },
        )

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_json(websocket, {"type": "error", "message": "无效 JSON"})
                continue

            mtype = str(msg.get("type", "")).lower()
            if mtype in {"ping", "heartbeat"}:
                await _send_json(websocket, {"type": "pong"})
            elif mtype == "resync":
                db.refresh(sess)
                state = _load_state(sess)
                view = _build_session_view(sess, state)
                cp = load_checkpoint(session_id)
                await _send_json(
                    websocket,
                    {
                        "type": "snapshot",
                        "data": view,
                        "checkpoint_seq": int((cp or {}).get("seq", 0)),
                    },
                )
            elif mtype == "answer":
                answer_text = str(msg.get("text", "")).strip()
                if not answer_text:
                    await _send_json(websocket, {"type": "error", "message": "回答不能为空"})
                    continue
                await _stream_answer(websocket, session_id, user_id, answer_text)
            else:
                await _send_json(websocket, {"type": "error", "message": f"未知消息类型: {mtype}"})
    except WebSocketDisconnect:
        logger.info("interview ws disconnected session_id=%s", session_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("interview ws error session_id=%s", session_id)
        try:
            await _send_json(websocket, {"type": "error", "message": str(e)})
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()
