"""可观测性 API：指标摘要 + 会话 trace（仅管理员）。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
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
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    sess = db.get(InterviewSession, session_id)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
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
        "timeline": _build_timeline(session_id, create_trace, guard_events),
    }


def _build_timeline(
    session_id: int,
    create_trace: dict | None,
    guard_events: list[dict],
) -> list[dict]:
    """合并 create / engine / guard 为按时间排序的时间线。"""
    events: list[dict] = []
    if create_trace:
        for step in create_trace.get("steps") or []:
            events.append(
                {
                    "kind": "create",
                    "ts": step.get("at") or create_trace.get("started_at"),
                    "node": step.get("step") or "step",
                    "duration_ms": round(float(step.get("duration_s") or 0) * 1000, 1),
                    "detail": {k: v for k, v in step.items() if k not in ("step", "at", "duration_s")},
                }
            )
    for row in read_session_trace(session_id):
        events.append(
            {
                "kind": "engine",
                "ts": row.get("ts"),
                "node": row.get("node"),
                "duration_ms": row.get("duration_ms"),
                "outcome": row.get("outcome"),
                "detail": {
                    k: v
                    for k, v in row.items()
                    if k not in ("ts", "node", "duration_ms", "outcome")
                },
            }
        )
    for row in guard_events:
        events.append(
            {
                "kind": "guard",
                "ts": row.get("ts"),
                "node": row.get("event") or "guard",
                "duration_ms": None,
                "outcome": "warn",
                "detail": {k: v for k, v in row.items() if k not in ("ts", "event")},
            }
        )

    def _sort_key(e: dict) -> str:
        return str(e.get("ts") or "")

    events.sort(key=_sort_key)
    return events
