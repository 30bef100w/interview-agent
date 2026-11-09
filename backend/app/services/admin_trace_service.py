"""会话 Trace 读取与时间线组装；运营和旧可观测性入口共用。"""
from collections import deque
from datetime import datetime, timezone
import json
import logging
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import InterviewSession
from app.schemas.admin import BUSINESS_TZ

logger = logging.getLogger(__name__)
TRACE_ROOT = Path(__file__).resolve().parents[2] / "logs"


def read_records(path: Path, limit: int) -> list[dict]:
    try:
        with path.open(encoding="utf-8") as stream:
            lines = deque(stream, maxlen=limit)
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError):
        logger.warning("无法读取 trace 文件 %s", path)
        return []
    records = []
    for line in lines:
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def build_timeline(create: dict | None, engine: list[dict], guards: list[dict]) -> list[dict]:
    events = []
    steps = (create or {}).get("steps")
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict):
            continue
        try:
            duration = round(float(step.get("duration_s") or 0) * 1000, 1)
        except (ValueError, TypeError):
            duration = None
        events.append({"kind": "create", "ts": step.get("at") or create.get("started_at"),
            "node": step.get("step") or "step", "duration_ms": duration,
            "detail": {k: v for k, v in step.items() if k not in ("step", "at", "duration_s")}})
    for row in engine:
        events.append({"kind": "engine", "ts": row.get("ts"), "node": row.get("node"),
            "duration_ms": row.get("duration_ms"), "outcome": row.get("outcome"),
            "detail": {k: v for k, v in row.items() if k not in ("ts", "node", "duration_ms", "outcome")}})
    for row in guards:
        events.append({"kind": "guard", "ts": row.get("ts"), "node": row.get("event") or "guard",
            "duration_ms": None, "outcome": "warn",
            "detail": {k: v for k, v in row.items() if k not in ("ts", "event")}})

    def sort_key(event):
        try:
            timestamp = datetime.fromisoformat(str(event.get("ts") or ""))
            return timestamp.replace(tzinfo=timestamp.tzinfo or BUSINESS_TZ).astimezone(timezone.utc).timestamp()
        except (ValueError, TypeError, OverflowError):
            return float("inf")

    return sorted(events, key=sort_key)


class AdminTraceService:
    def __init__(self, db: Session, root: Path | None = None):
        self.db = db
        self.root = root or TRACE_ROOT

    def trace(self, session_id: int) -> dict:
        if self.db.get(InterviewSession, session_id) is None:
            raise HTTPException(404, "会话不存在")
        try:
            value = json.loads((self.root / "create_trace" / f"{session_id}.json").read_text(encoding="utf-8"))
            create = value if isinstance(value, dict) else None
        except (OSError, ValueError, UnicodeError):
            create = None
        engine = read_records(self.root / "engine_trace" / f"{session_id}.jsonl", 200)
        guards = read_records(self.root / "session_guard" / f"{session_id}.jsonl", 80)
        return {"session_id": session_id, "engine_trace": engine, "create_trace": create,
                "guard_events": guards, "timeline": build_timeline(create, engine, guards)}
