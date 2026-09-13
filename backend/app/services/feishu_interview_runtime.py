"""把飞书通道接到现有面试引擎（共用规划 / 答题 / 退出）。"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import InterviewSession, Resume, ScoreReport, User, UserLlmSetting
from app.schemas.api import CreateSessionRequest
from app.services.billing import uses_platform_key
from app.services.feishu_channel import ChannelSession, ChannelUser

logger = logging.getLogger("app.feishu_interview")

_PLAN_TIMEOUT_S = 180
_PLAN_POLL_S = 2


class FeishuInterviewRuntime:
    def __init__(self, bind_map: dict[str, str] | None = None) -> None:
        self.bind_map = bind_map or {}

    def resolve_sender(self, open_id: str) -> ChannelUser | None:
        username = (self.bind_map.get(open_id) or "").strip()
        with SessionLocal() as db:
            user = None
            if username:
                user = db.scalars(select(User).where(User.username == username)).first()
            if user is None and open_id:
                user = db.scalars(select(User).where(User.feishu_open_id == open_id)).first()
            if user is None or int(user.is_disabled or 0) == 1:
                return None
            return ChannelUser(id=user.id, username=user.username)

    def latest_open_session(self, user_id: int) -> ChannelSession | None:
        with SessionLocal() as db:
            row = db.scalars(
                select(InterviewSession)
                .where(
                    InterviewSession.user_id == user_id,
                    InterviewSession.status.in_(("creating", "active")),
                )
                .order_by(InterviewSession.id.desc())
            ).first()
            return _view(row) if row else None

    def has_resume(self, user_id: int) -> bool:
        with SessionLocal() as db:
            return (
                db.scalars(
                    select(Resume.id).where(Resume.user_id == user_id).limit(1)
                ).first()
                is not None
            )

    def start_session(
        self,
        user: ChannelUser,
        *,
        role: str,
        company: str,
        rounds: int,
        interview_mode: str,
        interview_type: str,
        on_progress: Callable[[str], None],
        resume_id: int | None = None,
    ) -> ChannelSession:
        from app.api import interview as iv
        from app.services.billing import assert_platform_allowed

        db = SessionLocal()
        try:
            db_user = db.get(User, user.id)
            if db_user is None:
                return ChannelSession(id=0, status="failed", error="深问账号不存在")
            try:
                assert_platform_allowed(db, db_user)
            except HTTPException as exc:
                return ChannelSession(id=0, status="failed", error=str(exc.detail))
            resume = _pick_resume(db, user.id, resume_id)
            if resume is None:
                return ChannelSession(id=0, status="failed", error="还没有简历。")
            qcount = rounds if 4 <= int(rounds or 0) <= 20 else 8
            payload = CreateSessionRequest(
                resume_id=resume.id,
                interview_mode=interview_mode or "full",
                interview_type=interview_type or "full",
                question_count=qcount,
                target_role=(role or "").strip(),
                target_company=(company or "").strip(),
                skip_coding=bool(settings.feishu_skip_coding),
            )
            platform = uses_platform_key(db, db_user.id)
            session = InterviewSession(
                user_id=db_user.id,
                resume_id=resume.id,
                interview_mode=payload.interview_mode,
                interview_type=payload.interview_type,
                question_count=payload.question_count,
                status="creating",
                target_role=payload.target_role,
                target_company=payload.target_company,
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            sid = session.id
            meta = {
                "resume_id": resume.id,
                "practice_focus": "",
                "avoid_topics": iv._collect_avoid_topics(db, db_user.id, payload.dedup_scope),
                "asked_norms": sorted(
                    iv._collect_asked_norms(
                        db, db_user.id, payload.dedup_scope, payload.target_role
                    )
                ),
                "skip_coding": bool(payload.skip_coding),
                "platform": platform,
            }
        finally:
            db.close()

        iv._plan_session_background(sid, user.id, payload.model_dump(), meta)
        return self._wait_ready(sid, on_progress)

    def submit_answer(self, user: ChannelUser, session_id: int, text: str) -> dict:
        from app.api import interview as iv

        clipped = (text or "").strip()[:2000]
        db = SessionLocal()
        try:
            session = db.get(InterviewSession, session_id)
            db_user = db.get(User, user.id)
            if session is None or db_user is None or session.user_id != user.id:
                return {"message": "会话不存在", "finished": False}
            if session.status != "active":
                return {"message": "面试已结束", "finished": True}
            engine = iv._engine_for(db, db_user, session.id)
            out = iv._advance(session, db, clipped, engine)
            coding = False
            try:
                state = iv._load_state(session)
                if state.stage == "ASKING" and state.cursor < len(state.plan):
                    coding = str(state.plan[state.cursor].get("type") or "") == "coding"
            except Exception:  # noqa: BLE001
                coding = False
            out["coding"] = coding
            return out
        except HTTPException as exc:
            return {"message": str(exc.detail), "finished": False}
        except Exception:
            logger.exception("feishu submit_answer failed session=%s", session_id)
            return {
                "message": "这一轮引擎处理失败，本场进度还在。可以说「继续」再试，或到网页查看。",
                "finished": False,
            }
        finally:
            db.close()

    def abandon(self, user: ChannelUser, session_id: int) -> None:
        from app.api import interview as iv

        db = SessionLocal()
        try:
            session = db.get(InterviewSession, session_id)
            if session is None or session.user_id != user.id or session.status != "active":
                return
            state = iv._load_state(session)
            state.stage = "FINISHED"
            state.history.append(
                {
                    "role": "interviewer",
                    "text": "候选人选择中途退出本场面试。本场不生成完整报告，可随时再开一场独立模拟。",
                }
            )
            iv._save_state(session, state)
            session.status = "abandoned"
            session.finished_at = datetime.now(timezone.utc)
            db.commit()
        finally:
            db.close()

    def llm_for(self, user: ChannelUser):
        """管家判别用的 LLM，与面试同一套用户配置；不计场面用量。"""
        from app.services.llm.client import OpenAiLlm
        from app.services.llm.manager import resolve_llm_config

        with SessionLocal() as db:
            db_user = db.get(User, user.id)
            if db_user is None:
                return None
            setting = db.scalars(
                select(UserLlmSetting).where(UserLlmSetting.user_id == user.id)
            ).first()
            if setting is None:
                cfg = resolve_llm_config("deepseek", "deepseek-chat", "", use_default=True)
            else:
                cfg = resolve_llm_config(
                    setting.provider,
                    setting.model,
                    setting.api_key_encrypted,
                    bool(setting.is_default),
                )
        return OpenAiLlm(
            provider=cfg["provider"],
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            input_price_per_m=cfg["input_price_per_m"],
            output_price_per_m=cfg["output_price_per_m"],
        )

    def list_resumes(self, user: ChannelUser) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = db.scalars(
                select(Resume).where(Resume.user_id == user.id).order_by(Resume.id.desc())
            ).all()
            return [
                {
                    "id": r.id,
                    "filename": r.filename,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ]

    def list_sessions(self, user: ChannelUser, limit: int = 12) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = db.scalars(
                select(InterviewSession)
                .where(InterviewSession.user_id == user.id)
                .order_by(InterviewSession.id.desc())
                .limit(max(1, min(int(limit or 12), 30)))
            ).all()
            reported = set()
            if rows:
                reported = set(
                    db.scalars(
                        select(ScoreReport.session_id).where(
                            ScoreReport.session_id.in_([r.id for r in rows])
                        )
                    ).all()
                )
            return [_session_brief(r, r.id in reported) for r in rows]

    def get_session(self, user: ChannelUser, session_id: int) -> dict[str, Any]:
        from app.api import interview as iv

        with SessionLocal() as db:
            row = db.get(InterviewSession, session_id)
            if row is None or row.user_id != user.id:
                return {"error": "会话不存在"}
            has_report = (
                db.scalars(
                    select(ScoreReport.id).where(ScoreReport.session_id == row.id)
                ).first()
                is not None
            )
            last = ""
            stage = row.stages or ""
            coding = False
            if row.state_json:
                try:
                    state = iv._load_state(row)
                    stage = state.stage
                    last = _last_interviewer_text(state)
                    if state.stage == "ASKING" and state.cursor < len(state.plan or []):
                        coding = str(state.plan[state.cursor].get("type") or "") == "coding"
                except Exception:  # noqa: BLE001
                    last = ""
            brief = _session_brief(row, has_report)
            brief.update(
                {
                    "stage": stage,
                    "coding": coding,
                    "last_interviewer": last[:400],
                }
            )
            return brief

    def get_account(self, user: ChannelUser) -> dict[str, Any]:
        with SessionLocal() as db:
            db_user = db.get(User, user.id)
            if db_user is None:
                return {"error": "深问账号不存在"}
            n = len(
                db.scalars(select(Resume.id).where(Resume.user_id == user.id)).all()
            )
            return {
                "username": db_user.username,
                "has_resume": n > 0,
                "resume_count": n,
                "platform_quota": int(db_user.platform_quota or 0),
                "uses_platform_key": uses_platform_key(db, db_user.id),
            }

    def resume_session(self, user: ChannelUser, session_id: int) -> dict[str, Any]:
        from app.api import interview as iv

        db = SessionLocal()
        try:
            session = db.get(InterviewSession, session_id)
            if session is None or session.user_id != user.id:
                return {"ok": False, "error": "会话不存在"}
            has_report = (
                db.scalars(
                    select(ScoreReport.id).where(ScoreReport.session_id == session.id)
                ).first()
                is not None
            )
            if session.status == "finished" or has_report:
                return {"ok": False, "error": "这场已经出报告，不能续，只能新开一场。"}
            if session.status == "creating":
                db.close()
                db = None
                ready = self._wait_ready(session_id, lambda _t: None)
                if ready.status != "active":
                    return {"ok": False, "error": ready.error or "题单还在规划"}
                return self.resume_session(user, session_id)
            if session.status == "abandoned":
                try:
                    state = iv._load_state(session)
                except Exception as exc:  # noqa: BLE001
                    return {"ok": False, "error": f"无法恢复本场：{exc}"}
                if state.history and "中途退出本场面试" in str(
                    (state.history[-1] or {}).get("text") or ""
                ):
                    state.history.pop()
                has_candidate = any(
                    (h or {}).get("role") == "candidate" for h in (state.history or [])
                )
                if has_candidate or int(state.cursor or 0) > 0:
                    state.stage = "ASKING"
                else:
                    state.stage = "INTRO"
                iv._save_state(session, state)
                session.status = "active"
                session.finished_at = None
                db.commit()
            if session.status != "active":
                return {"ok": False, "error": "这场现在不能继续。"}
            try:
                state = iv._load_state(session)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"会话状态缺失：{exc}"}
            coding = False
            if state.stage == "ASKING" and state.cursor < len(state.plan or []):
                coding = str(state.plan[state.cursor].get("type") or "") == "coding"
            return {
                "ok": True,
                "session_id": session.id,
                "status": session.status,
                "stage": state.stage,
                "message": _last_interviewer_text(state),
                "url": self.session_url(session.id),
                "coding": coding,
            }
        finally:
            if db is not None:
                db.close()

    def session_url(self, session_id: int) -> str:
        origin = (settings.public_origin or "").strip().rstrip("/")
        if not origin:
            return ""
        return f"{origin}/interview/{session_id}"

    def _wait_ready(self, session_id: int, on_progress: Callable[[str], None]) -> ChannelSession:
        from app.api import interview as iv

        deadline = time.monotonic() + _PLAN_TIMEOUT_S
        last_label = ""
        while time.monotonic() < deadline:
            with SessionLocal() as db:
                row = db.get(InterviewSession, session_id)
                if row is None:
                    return ChannelSession(id=session_id, status="failed", error="会话丢失")
                if row.status == "active":
                    return _view(row)
                if row.status == "failed":
                    return ChannelSession(id=session_id, status="failed", error="规划失败")
            progress, label, _step = iv._read_create_progress(session_id)
            if label and label != last_label:
                last_label = label
                on_progress(f"规划中 {progress}% · {label}")
            time.sleep(_PLAN_POLL_S)
        logger.warning("feishu plan timeout session=%s", session_id)
        return ChannelSession(id=session_id, status="failed", error="规划超时，请稍后重试。")


def _view(row: InterviewSession) -> ChannelSession:
    from app.api import interview as iv

    stage = ""
    coding = False
    if row.state_json:
        try:
            state = iv._load_state(row)
            stage = state.stage
            if state.stage == "ASKING" and state.cursor < len(state.plan or []):
                coding = str(state.plan[state.cursor].get("type") or "") == "coding"
        except Exception:  # noqa: BLE001
            stage = row.stages or ""
    return ChannelSession(id=row.id, status=row.status, stage=stage, coding=coding)


def _pick_resume(db, user_id: int, resume_id: int | None) -> Resume | None:
    if resume_id:
        row = db.get(Resume, resume_id)
        if row is not None and row.user_id == user_id:
            return row
        return None
    return db.scalars(
        select(Resume).where(Resume.user_id == user_id).order_by(Resume.id.desc())
    ).first()


def _session_brief(row: InterviewSession, has_report: bool) -> dict[str, Any]:
    resumable = (not has_report) and row.status in {"creating", "active", "abandoned"}
    return {
        "id": row.id,
        "status": row.status,
        "target_role": row.target_role or "",
        "target_company": row.target_company or "",
        "mode": row.interview_mode,
        "type": row.interview_type,
        "rounds_used": row.rounds_used,
        "question_count": row.question_count,
        "started_at": row.started_at.isoformat() if row.started_at else "",
        "has_report": has_report,
        "resumable": resumable,
    }


def _last_interviewer_text(state) -> str:
    for item in reversed(state.history or []):
        if (item or {}).get("role") == "interviewer":
            text = str(item.get("text") or "").strip()
            if text:
                return text
    intro = str(getattr(state, "intro_text", "") or "").strip()
    return intro or "本场已就绪，请继续作答。"
