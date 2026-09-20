from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InterviewSession, LLMUsage


def _iso(value: datetime | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _naive(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min
    if value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def summarize_user_usage(db: Session, user_id: int, *, recent_limit: int = 50) -> dict:
    rows = db.scalars(select(LLMUsage).where(LLMUsage.user_id == user_id)).all()
    total_in = sum(int(r.input_tokens or 0) for r in rows)
    total_out = sum(int(r.output_tokens or 0) for r in rows)
    total_cost = sum(float(r.cost_yuan or 0) for r in rows)

    session_ids = {int(r.session_id) for r in rows if r.session_id}
    own_sessions: dict[int, InterviewSession] = {}
    if session_ids:
        for sess in db.scalars(
            select(InterviewSession).where(
                InterviewSession.user_id == user_id,
                InterviewSession.id.in_(session_ids),
            )
        ).all():
            own_sessions[int(sess.id)] = sess

    buckets: dict[int, dict] = {}
    for r in rows:
        if not r.session_id:
            continue
        sid = int(r.session_id)
        sess = own_sessions.get(sid)
        if sess is None:
            continue
        b = buckets.get(sid)
        if b is None:
            b = {
                "session_id": sid,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_yuan": 0.0,
                "call_count": 0,
                "last_at": r.created_at,
                "providers": Counter(),
                "models": Counter(),
            }
            buckets[sid] = b
        b["input_tokens"] += int(r.input_tokens or 0)
        b["output_tokens"] += int(r.output_tokens or 0)
        b["cost_yuan"] += float(r.cost_yuan or 0)
        b["call_count"] += 1
        if r.created_at and (b["last_at"] is None or _naive(r.created_at) > _naive(b["last_at"])):
            b["last_at"] = r.created_at
        if r.provider:
            b["providers"][r.provider] += 1
        if r.model:
            b["models"][r.model] += 1

    ordered = sorted(
        buckets.values(),
        key=lambda item: _naive(item["last_at"]),
        reverse=True,
    )
    recent = []
    for b in ordered[:recent_limit]:
        sess = own_sessions[b["session_id"]]
        provider = b["providers"].most_common(1)[0][0] if b["providers"] else ""
        model = b["models"].most_common(1)[0][0] if b["models"] else ""
        recent.append(
            {
                "session_id": b["session_id"],
                "provider": provider,
                "model": model,
                "call_count": b["call_count"],
                "input_tokens": b["input_tokens"],
                "output_tokens": b["output_tokens"],
                "cost_yuan": round(b["cost_yuan"], 4),
                "created_at": _iso(b["last_at"]),
                "target_role": sess.target_role or "",
                "target_company": sess.target_company or "",
                "status": sess.status or "",
            }
        )

    return {
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_cost_yuan": round(total_cost, 4),
        "session_count": len(buckets),
        "recent": recent,
    }
