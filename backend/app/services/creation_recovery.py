"""Make interrupted creation terminal and refund reserved quota exactly once.

This is bounded failure recovery, not a durable queue or automatic model replay.
"""
import time

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import InterviewSession
from app.services.billing import refund_session_quota

CREATION_TIMEOUT_SECONDS = 20 * 60


def fail_creation(db: Session, session_id: int, *, expired_only: bool = False) -> bool:
    query = update(InterviewSession).where(
        InterviewSession.id == session_id, InterviewSession.status == "creating",
    )
    if expired_only:
        query = query.where(InterviewSession.creation_deadline <= time.time())
    changed = db.execute(query.values(status="failed", version=InterviewSession.version + 1)
                         .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        return False
    refund_session_quota(db, session_id)
    db.commit()
    return True


def recover_expired_creations(db: Session) -> int:
    ids = list(db.scalars(select(InterviewSession.id).where(
        InterviewSession.status == "creating", InterviewSession.creation_deadline <= time.time(),
    )))
    return sum(fail_creation(db, sid, expired_only=True) for sid in ids)
