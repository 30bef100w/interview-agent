"""可观测性 API：指标摘要 + 会话 trace（运维 / 本人会话调试）。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.db import get_db
from app.models import InterviewSession, User
from app.observability.metrics import metrics_registry
from app.observability.node_trace import read_session_trace

router = APIRouter(prefix="/api/observability", tags=["observability"])

_CREATE_TRACE = Path(__file__).resolve().parents[2] / "logs" / "create_trace"
_GUARD_DIR = Path(__file__).resolve().parents[2] / "logs" / "session_guard"


@router.get("/metrics")
def observability_metrics(admin: User = Depends(require_admin)) -> dict:
    return metrics_registry.snapshot()


@router.get("/sessions/{session_id}/trace")
def session_trace(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    sess = db.get(InterviewSession, session_id)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    if sess.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看")
    create_trace = None
    cp = _CREATE_TRACE / f"{session_id}.json"
    if cp.exists():
        try:
            create_trace = json.loads(cp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            create_trace = None
    guard_events: list[dict] = []
    gp = _GUARD_DIR / f"{session_id}.jsonl"
    if gp.exists():
        for line in gp.read_text(encoding="utf-8").strip().splitlines()[-80:]:
            try:
                guard_events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {
        "session_id": session_id,
        "engine_trace": read_session_trace(session_id),
        "create_trace": create_trace,
        "guard_events": guard_events,
    }
