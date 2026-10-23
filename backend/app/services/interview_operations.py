"""Short-transaction command claims shared by HTTP/SSE/WS/code/Feishu.

No database row lock is held during model execution. A persisted claim prevents
concurrent work; SQLAlchemy versioning fences an expired worker's final commit.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Callable

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.models import InterviewOperation, InterviewSession

OPERATION_TIMEOUT_SECONDS = 20 * 60


def recover_expired_operations(db: Session) -> int:
    """Release abandoned claims even when no client sends another command."""
    expired = list(db.execute(select(InterviewSession.id, InterviewSession.pending_operation).where(
        InterviewSession.pending_operation.is_not(None), InterviewSession.operation_deadline <= time.time(),
    )))
    count = 0
    for sid, request_id in expired:
        changed = db.execute(update(InterviewSession).where(
            InterviewSession.id == sid, InterviewSession.pending_operation == request_id,
            InterviewSession.operation_deadline <= time.time(),
        ).values(pending_operation=None, operation_deadline=None, version=InterviewSession.version + 1)
          .execution_options(synchronize_session=False))
        if changed.rowcount:
            db.execute(update(InterviewOperation).where(
                InterviewOperation.session_id == sid, InterviewOperation.request_id == request_id,
                InterviewOperation.status == "processing",
            ).values(status="expired"))
            count += 1
    if expired:
        db.commit()
    return count


def run_operation(
    db: Session, session_id: int, user_id: int, kind: str, payload: dict,
    action: Callable[[InterviewSession], dict],
) -> dict:
    session = db.get(InterviewSession, session_id, populate_existing=True)
    if session is None or session.user_id != user_id:
        raise HTTPException(404, "面试会话不存在")
    request_id = payload.get("submission_id") or uuid.uuid4().hex
    content = {k: v for k, v in payload.items() if k not in {"submission_id", "expected_version"}}
    fingerprint = hashlib.sha256(json.dumps([kind, content], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    previous = db.scalar(select(InterviewOperation).where(
        InterviewOperation.session_id == session_id, InterviewOperation.request_id == request_id,
    ))
    if previous:
        if previous.fingerprint != fingerprint:
            raise HTTPException(409, "提交编号已用于其他内容，请刷新后重试")
        if previous.status == "done":
            return json.loads(previous.result_json)
        if previous.status != "processing":
            raise HTTPException(409, "上次提交未完成，请刷新进度后重新提交")

    now = time.time()
    if session.pending_operation and (session.operation_deadline or 0) <= now:
        old_id = session.pending_operation
        released = db.execute(update(InterviewSession).where(
            InterviewSession.id == session_id,
            InterviewSession.pending_operation == old_id,
            InterviewSession.operation_deadline <= now,
        ).values(pending_operation=None, operation_deadline=None,
                 version=InterviewSession.version + 1).execution_options(synchronize_session=False))
        if released.rowcount:
            db.execute(update(InterviewOperation).where(
                InterviewOperation.session_id == session_id,
                InterviewOperation.request_id == old_id,
                InterviewOperation.status == "processing",
            ).values(status="expired"))
        db.commit()
        db.refresh(session)
        raise HTTPException(409, "上次处理超时，进度已保留，请刷新后重新提交")
    if session.pending_operation:
        raise HTTPException(409, "本场正在处理另一项操作，请稍后刷新进度")
    if previous:
        raise HTTPException(409, "上次提交未完成，请刷新后重新提交")
    if session.status != "active":
        raise HTTPException(409, "面试已结束或尚未就绪")
    expected = payload.get("expected_version")
    if expected is not None and expected != session.version:
        raise HTTPException(409, "面试进度已更新，请刷新后再提交")
    claimed = db.execute(update(InterviewSession).where(
        InterviewSession.id == session_id, InterviewSession.version == session.version,
        InterviewSession.status == "active", InterviewSession.pending_operation.is_(None),
    ).values(pending_operation=request_id, operation_deadline=now + OPERATION_TIMEOUT_SECONDS,
             version=InterviewSession.version + 1).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "面试进度已更新，请刷新后再提交")
    operation = InterviewOperation(session_id=session_id, request_id=request_id,
                                   fingerprint=fingerprint, status="processing")
    db.add(operation)
    db.commit()
    db.refresh(session)
    try:
        result = action(session)
        session.pending_operation = None
        session.operation_deadline = None
        session.last_submission_id = request_id
        operation.status = "done"
        operation.result_json = json.dumps(result, ensure_ascii=False)
        db.commit()  # State, answers, report, usage and acknowledgement commit together.
        return result
    except Exception as exc:
        db.rollback()
        db.execute(update(InterviewSession).where(
            InterviewSession.id == session_id, InterviewSession.pending_operation == request_id,
        ).values(pending_operation=None, operation_deadline=None,
                 version=InterviewSession.version + 1).execution_options(synchronize_session=False))
        db.execute(update(InterviewOperation).where(
            InterviewOperation.session_id == session_id, InterviewOperation.request_id == request_id,
            InterviewOperation.status == "processing",
        ).values(status="failed"))
        db.commit()
        if isinstance(exc, StaleDataError):
            raise HTTPException(409, "面试进度已变化，本次结果未覆盖新进度，请刷新") from exc
        raise
