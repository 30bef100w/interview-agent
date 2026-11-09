"""保留可观测性入口，复用运营层的 Trace 查询。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db import get_db
from app.observability.metrics import metrics_registry
from app.schemas.admin import MAX_DATABASE_ID
from app.services.admin_trace_service import AdminTraceService

router = APIRouter(prefix="/api/observability", tags=["observability"], dependencies=[Depends(require_admin)])


@router.get("/metrics")
def observability_metrics() -> dict:
    return metrics_registry.snapshot()


@router.get("/sessions/{session_id}/trace")
def session_trace(session_id: Annotated[int, Path(gt=0, le=MAX_DATABASE_ID)], db: Session = Depends(get_db)) -> dict:
    return AdminTraceService(db).trace(session_id)
