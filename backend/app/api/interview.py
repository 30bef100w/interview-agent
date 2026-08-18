"""面试会话 API：创建会话（开场）→ 提交回答推进状态机 → 写 Question/Answer/ScoreReport 行。

answer 接口有两个版本：普通 JSON（兼容旧客户端/脚本）与 SSE 流式（前端打字机）。
"""
import json
import re
import queue
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models import (
    Answer,
    InterviewSession,
    LLMUsage,
    Question,
    Resume,
    ScoreReport,
    User,
    UserLlmSetting,
)
from app.schemas.api import AnswerOut, AnswerRequest, CreateSessionRequest, SessionOut
from app.schemas.interview import InterviewState
from app.services.billing import (
    assert_platform_allowed,
    deduct_platform_quota,
    touch_active,
    uses_platform_key,
)
from app.services.interviewer_engine import InterviewEngine
from app.services.llm.client import OpenAiLlm, StreamingLlm, UsageSink
from app.services.llm.manager import resolve_llm_config

router = APIRouter(prefix="/api/interview", tags=["interview"])


def _engine_for(
    db: Session,
    user: User,
    session_id: int | None = None,
    *,
    enforce_quota: bool = True,
) -> InterviewEngine:
    """按用户 LLM 配置构造引擎（带用量统计）；未配置的用户走系统默认 key。"""
    if enforce_quota:
        assert_platform_allowed(db, user)
    platform = uses_platform_key(db, user.id)
    setting = db.scalars(
        select(UserLlmSetting).where(UserLlmSetting.user_id == user.id)
    ).first()
    if setting is None:
        cfg = resolve_llm_config("deepseek", "deepseek-chat", "", use_default=True)
    else:
        cfg = resolve_llm_config(
            setting.provider, setting.model, setting.api_key_encrypted, bool(setting.is_default)
        )
    sink = UsageSink(user.id, session_id, db, used_platform_key=platform)
    llm = OpenAiLlm(
        provider=cfg["provider"],
        model=cfg["model"],
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        input_price_per_m=cfg["input_price_per_m"],
        output_price_per_m=cfg["output_price_per_m"],
        on_usage=sink.record,
    )
    return InterviewEngine(llm)


def _get_owned_session(db: Session, session_id: int, user_id: int) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="面试会话不存在")
    return session


def _load_state(session: InterviewSession) -> InterviewState:
    if not session.state_json:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="会话状态缺失")
    return InterviewState.from_dict(json.loads(session.state_json))


def _save_state(session: InterviewSession, state: InterviewState) -> None:
    session.state_json = json.dumps(state.to_dict(), ensure_ascii=False)
    session.stages = state.stage
    session.current_q_index = state.cursor
    session.rounds_used = state.rounds_used
    session.plan_json = json.dumps(state.plan, ensure_ascii=False)


def _collect_avoid_topics(db: Session, user_id: int, scope: str) -> list[str]:
    """按去重范围收集历史题主题/题干摘要，供规划官避开 + 规划后相似检查。"""
    if scope == "none":
        return []
    # all = 永久去重：尽量拉全量历史场次
    limit = {"last5": 5, "last10": 10, "all": 300}.get(scope, 0)
    if limit <= 0:
        return []
    rows = db.scalars(
        select(InterviewSession)
        .where(
            InterviewSession.user_id == user_id,
            InterviewSession.plan_json.is_not(None),
        )
        .order_by(InterviewSession.id.desc())
        .limit(limit)
    ).all()
    topics: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        key = text[:80]
        if key in seen:
            return
        seen.add(key)
        topics.append(text[:200])

    for s in rows:
        try:
            plan = json.loads(s.plan_json or "[]")
        except json.JSONDecodeError:
            plan = []
        for q in plan:
            if not isinstance(q, dict):
                continue
            _add(str(q.get("topic") or ""))
            _add(str(q.get("text") or ""))
            _add(str(q.get("bank_question") or ""))
            if q.get("type") == "coding" and q.get("slug"):
                _add(f"coding:{q['slug']}")
        # 库内 Question 原文（实际问出口语，规划后检查主要靠这个）
        qrows = db.scalars(
            select(Question).where(Question.session_id == s.id).limit(40)
        ).all()
        for qr in qrows:
            _add(qr.text or "")
        if len(topics) >= 400:
            break
    return topics[:400]


def _collect_asked_norms(db: Session, user_id: int, scope: str, target_role: str) -> set[str]:
    """召回去重：历史面试问过的完整题目（归一化），检索时重罚/几乎排除。

    来源：ScoreReport.per_question + Question 表 + plan 里 bank_question。
    """
    if scope == "none":
        return set()
    limit = {"last5": 5, "last10": 10, "all": 300}.get(scope, 0)
    if limit <= 0:
        return set()
    rows = db.scalars(
        select(InterviewSession)
        .where(InterviewSession.user_id == user_id)
        .order_by(InterviewSession.id.desc())
        .limit(limit * 2)
    ).all()
    if target_role:
        same = [r for r in rows if (r.target_role or "") == target_role][:limit]
        if len(same) < max(1, limit // 2):
            same += [r for r in rows if r not in same][: limit - len(same)]
        rows = same
    else:
        rows = rows[:limit]

    norms: set[str] = set()

    def _add_norm(text: str) -> None:
        t = re.sub(r"\W+", "", (text or "").lower())
        if len(t) >= 8:
            norms.add(t)

    for s in rows:
        rep = db.scalars(
            select(ScoreReport).where(ScoreReport.session_id == s.id)
        ).first()
        if rep:
            try:
                report = json.loads(rep.report_json)
            except json.JSONDecodeError:
                report = {}
            for q in report.get("per_question") or []:
                _add_norm(str(q.get("question") or ""))
        qrows = db.scalars(
            select(Question).where(Question.session_id == s.id).limit(40)
        ).all()
        for qr in qrows:
            _add_norm(qr.text or "")
        try:
            plan = json.loads(s.plan_json or "[]")
        except json.JSONDecodeError:
            plan = []
        for q in plan:
            if not isinstance(q, dict):
                continue
            _add_norm(str(q.get("bank_question") or ""))
            _add_norm(str(q.get("text") or ""))
            _add_norm(str(q.get("topic") or ""))
    return norms


def _review_focus_hint(db: Session, user_id: int) -> str:
    """复习模式：从成长档案取最高优建议的 practice_focus。"""
    from app.services.growth import build_growth_timeline

    sessions = db.scalars(
        select(InterviewSession)
        .where(
            InterviewSession.user_id == user_id,
            InterviewSession.status == "finished",
        )
        .order_by(InterviewSession.started_at.asc())
        .limit(50)
    ).all()
    if not sessions:
        return ""
    reports = {
        r.session_id: r
        for r in db.scalars(
            select(ScoreReport).where(ScoreReport.session_id.in_([s.id for s in sessions]))
        ).all()
    }
    rows = []
    for s in sessions:
        rep = reports.get(s.id)
        if not rep:
            continue
        try:
            report = json.loads(rep.report_json)
        except json.JSONDecodeError:
            continue
        rows.append(
            {
                "session_id": s.id,
                "started_at": s.started_at.isoformat() if s.started_at else "",
                "mode": s.interview_mode,
                "type": s.interview_type,
                "target_role": s.target_role or "",
                "report": report,
            }
        )
    if not rows:
        return ""
    data = build_growth_timeline(rows)
    suggestions = data.get("practice_suggestions") or []
    for s in suggestions:
        focus = (s.get("practice_focus") or "").strip()
        if focus and s.get("kind") != "default":
            return focus[:500]
    gaps = data.get("recurring_gaps") or []
    if gaps:
        texts = []
        for g in gaps[:5]:
            if isinstance(g, dict):
                texts.append(str(g.get("text") or "")[:40])
            else:
                texts.append(str(g)[:40])
        texts = [t for t in texts if t]
        if texts:
            return "本场请优先复盘以下反复短板：" + "；".join(texts)
    return ""


def _validated_report(
    session: InterviewSession, report: dict, db: Session | None = None
) -> dict:
    """对外展示前再跑引擎硬校验，保证逐题分是校验后的最终分。"""
    if not isinstance(report, dict):
        return {}
    report = dict(report)
    report.pop("per_question_calibrated", None)
    if not session.state_json or db is None:
        return report
    try:
        state = InterviewState.from_dict(json.loads(session.state_json))
        user = db.get(User, session.user_id)
        if user is None:
            return report
        engine = _engine_for(db, user, session.id, enforce_quota=False)
        return engine._sanitize_report(state, report)
    except Exception:
        return report


def _question_row(db: Session, session_id: int, q_index: int, q: dict) -> Question:
    row = Question(
        session_id=session_id,
        q_index=q_index,
        question_type="qa",
        text=q["text"],
        rubric_json=q.get("rubric") or None,
    )
    db.add(row)
    db.flush()
    return row


def _answer_row(
    db: Session, session_id: int, question_id: int, text: str, pq: dict
) -> None:
    score = pq.get("score")
    db.add(
        Answer(
            session_id=session_id,
            question_id=question_id,
            content=text,
            score_json=json.dumps(
                {k: pq.get(k) for k in ("score", "strengths", "weaknesses")},
                ensure_ascii=False,
            )
            if score is not None
            else None,
        )
    )


@router.get("/session/{session_id}")
def get_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = _get_owned_session(db, session_id, current_user.id)
    state = _load_state(session)
    current_coding = None
    if state.stage == "ASKING" and state.cursor < len(state.plan):
        q = state.plan[state.cursor]
        if q["type"] == "coding":
            from app.services.question_bank import build_problem_view

            current_coding = build_problem_view(q.get("slug", ""))
    return {
        "session_id": session.id,
        "mode": session.interview_mode,
        "type": session.interview_type,
        "status": session.status,
        "stage": state.stage,
        "history": state.history,
        "topics": [q["topic"] for q in state.plan],
        "current_coding": current_coding,
        "rounds_used": state.rounds_used,
        "total_rounds": state.total_rounds,
    }


@router.post("/session/{session_id}/abandon")
def abandon_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """中途退出：结束本场但不生成报告。可从历史里看到「已退出」。"""
    session = _get_owned_session(db, session_id, current_user.id)
    if session.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="面试已结束")
    state = _load_state(session)
    state.stage = "FINISHED"
    state.history.append(
        {
            "role": "interviewer",
            "text": "候选人选择中途退出本场面试。本场不生成完整报告，可随时再开一场独立模拟。",
        }
    )
    _save_state(session, state)
    session.status = "abandoned"
    session.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "session_id": session.id,
        "status": session.status,
        "stage": state.stage,
        "message": "已退出本场面试",
    }


@router.get("/session/{session_id}/report")
def get_report(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = _get_owned_session(db, session_id, current_user.id)
    report_row = db.scalars(
        select(ScoreReport).where(ScoreReport.session_id == session_id)
    ).first()
    if report_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="报告尚未生成"
        )
    report = _validated_report(session, json.loads(report_row.report_json), db)
    return {
        "session_id": session.id,
        "mode": session.interview_mode,
        "type": session.interview_type,
        "created_at": report_row.created_at,
        "report": report,
    }


@router.get("/session/{session_id}/report/export")
def export_report(
    session_id: int,
    format: str = "docx",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """面试报告导出为 Word（.docx）或 PDF。"""
    from app.services.report_export import build_report_docx
    from app.services.report_pdf import build_report_pdf

    session = _get_owned_session(db, session_id, current_user.id)
    report_row = db.scalars(
        select(ScoreReport).where(ScoreReport.session_id == session_id)
    ).first()
    if report_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="报告尚未生成"
        )
    report = _validated_report(session, json.loads(report_row.report_json), db)
    mode_label = (
        "全流程混合面"
        if session.interview_mode == "full"
        else f"专项专场 · {session.interview_type}"
    )
    meta = {
        "mode_label": mode_label,
        "created_at": report_row.created_at.strftime("%Y-%m-%d %H:%M"),
    }
    fmt = (format or "docx").lower()
    if fmt == "pdf":
        buf = build_report_pdf(report, meta)
        return Response(
            content=buf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="interview_report_{session_id}.pdf"'
            },
        )
    buf = build_report_docx(report, meta)
    return Response(
        content=buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="interview_report_{session_id}.docx"'
        },
    )


@router.post("/session", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionOut:
    # 平台 Key 额度门禁：用尽则禁止创建（自填 Key 不扣次）
    assert_platform_allowed(db, current_user)
    platform = uses_platform_key(db, current_user.id)

    resume = db.get(Resume, payload.resume_id)
    if resume is None or resume.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历不存在")
    profile = json.loads(resume.profile_json) if resume.profile_json else {}

    session = InterviewSession(
        user_id=current_user.id,
        resume_id=resume.id,
        interview_mode=payload.interview_mode,
        interview_type=payload.interview_type,
        question_count=payload.question_count,
        status="active",
        target_role=(payload.target_role or "").strip(),
        target_company=(payload.target_company or "").strip(),
    )
    db.add(session)
    db.flush()  # 先拿 session.id 再跑引擎（引擎内 history 记录不依赖 id，但报告引用）

    practice_focus = (payload.practice_focus or "").strip()
    if payload.review_mode:
        review_hint = _review_focus_hint(db, current_user.id)
        if review_hint:
            practice_focus = (
                f"{practice_focus}\n{review_hint}".strip()
                if practice_focus
                else review_hint
            )[:500]

    avoid_topics = _collect_avoid_topics(db, current_user.id, payload.dedup_scope)
    asked_norms = _collect_asked_norms(
        db, current_user.id, payload.dedup_scope, (payload.target_role or "").strip()
    )
    skip_coding = bool(payload.skip_coding) and payload.interview_mode == "full"

    state, opening = _engine_for(db, current_user, session.id).create(
        session.id,
        resume.raw_text,
        profile,
        payload.question_count,
        payload.interview_mode,
        payload.interview_type,
        target_role=payload.target_role or "",
        target_company=payload.target_company or "",
        practice_focus=practice_focus,
        skip_coding=skip_coding,
        review_mode=bool(payload.review_mode),
        avoid_topics=avoid_topics,
        asked_norms=asked_norms,
    )
    _save_state(session, state)
    quota_remaining = int(current_user.platform_quota or 0)
    if platform:
        quota_remaining = deduct_platform_quota(db, current_user)
    touch_active(current_user)
    db.commit()
    plan_types = [str(q.get("type") or "") for q in (state.plan or [])]
    return SessionOut(
        session_id=session.id,
        status=session.status,
        stage=state.stage,
        message=opening,
        settings_applied={
            "skip_coding": skip_coding,
            "has_coding": "coding" in plan_types,
            "plan_types": plan_types,
            "dedup_scope": payload.dedup_scope,
            "avoid_topic_count": len(avoid_topics),
            "review_mode": bool(payload.review_mode),
            "question_count": payload.question_count,
            "used_platform_key": platform,
            "platform_quota_remaining": quota_remaining,
        },
    )


def _advance(
    session: InterviewSession, db: Session, text: str, engine: InterviewEngine
) -> dict:
    """推进状态机并写库。返回 {message, stage, status, finished, report}。"""
    state = _load_state(session)
    before_cursor = state.cursor
    report = None

    if state.stage == "INTRO":
        state, message = engine.handle_intro(state, text)
        _question_row(db, session.id, 0, state.plan[0])
    elif state.stage == "ASKING":
        state, message = engine.handle_answer(state, text)
        q = state.plan[before_cursor]
        qrow = db.scalars(
            select(Question).where(
                Question.session_id == session.id,
                Question.q_index == before_cursor,
            )
        ).first()
        if qrow is None:
            qrow = _question_row(db, session.id, before_cursor, q)
        if state.cursor == before_cursor:
            qrow.follow_up_count += 1  # 追问，题目未前进
        _answer_row(db, session.id, qrow.id, text, state.per_question[f"q{before_cursor + 1}"])
    elif state.stage == "ASK_BACK":
        state, report = engine.handle_ask_back(state, text)
        session.status = "finished"
        session.finished_at = datetime.now(timezone.utc)
        db.add(
            ScoreReport(
                session_id=session.id,
                report_json=json.dumps(report, ensure_ascii=False),
            )
        )
        message = "面试结束，报告已生成。"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="面试阶段异常")

    _save_state(session, state)
    db.commit()
    return {
        "message": message,
        "stage": state.stage,
        "status": session.status,
        "finished": session.status == "finished",
        "report": report,
    }


@router.post("/session/{session_id}/answer", response_model=AnswerOut)
def submit_answer(
    session_id: int,
    payload: AnswerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnswerOut:
    session = _get_owned_session(db, session_id, current_user.id)
    if session.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="面试已结束")

    out = _advance(session, db, payload.text, _engine_for(db, current_user, session.id))
    return AnswerOut(**out)


@router.post("/session/{session_id}/answer/stream")
def submit_answer_stream(
    session_id: int,
    payload: AnswerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """SSE 流式回答接口：面试官消息逐 token 下发，结束事件带最终状态。

    事件：token（消息片段）/ done（最终 JSON：message/stage/status/finished/report）/ error。
    """
    session = _get_owned_session(db, session_id, current_user.id)
    if session.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="面试已结束")

    def event_stream():
        q: queue.Queue = queue.Queue()
        engine = _engine_for(db, current_user, session.id)
        stream_engine = InterviewEngine(
            StreamingLlm(engine.llm, lambda tok: q.put(("token", tok)))
        )

        def producer() -> None:
            try:
                out = _advance(session, db, payload.text, stream_engine)
                q.put(("done", out))
            except Exception as e:  # noqa: BLE001  线程内异常转为 error 事件
                q.put(("error", str(e)))

        threading.Thread(target=producer, daemon=True).start()
        while True:
            kind, data = q.get()
            yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if kind in ("done", "error"):
                return

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/history")
def get_history(
    q: str = "",
    status: str = "",
    target_role: str = "",
    target_company: str = "",
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """历史列表：支持搜索、状态、目标岗位/企业筛选与分页。"""
    page = max(1, page)
    page_size = min(max(1, page_size), 50)

    stmt = select(InterviewSession).where(InterviewSession.user_id == current_user.id)
    if status:
        stmt = stmt.where(InterviewSession.status == status)
    if target_role.strip():
        stmt = stmt.where(InterviewSession.target_role.contains(target_role.strip()))
    if target_company.strip():
        stmt = stmt.where(InterviewSession.target_company.contains(target_company.strip()))

    rows = db.scalars(stmt.order_by(InterviewSession.started_at.desc())).all()

    # 关键词搜索：模式文案 / 类型 / 岗位 / 企业
    keyword = q.strip().lower()
    if keyword:
        filtered = []
        for r in rows:
            blob = " ".join(
                [
                    r.interview_mode or "",
                    r.interview_type or "",
                    r.target_role or "",
                    r.target_company or "",
                    r.status or "",
                ]
            ).lower()
            if keyword in blob:
                filtered.append(r)
        rows = filtered

    total = len(rows)
    start = (page - 1) * page_size
    page_rows = rows[start : start + page_size]

    reported: set[int] = set()
    if page_rows:
        reported = set(
            db.scalars(
                select(ScoreReport.session_id).where(
                    ScoreReport.session_id.in_([r.id for r in page_rows])
                )
            ).all()
        )

    items = [
        {
            "session_id": r.id,
            "mode": r.interview_mode,
            "type": r.interview_type,
            "status": r.status,
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "rounds_used": r.rounds_used,
            "question_count": r.question_count,
            "has_report": r.id in reported,
            "target_role": getattr(r, "target_role", "") or "",
            "target_company": getattr(r, "target_company", "") or "",
        }
        for r in page_rows
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/growth")
def get_growth(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """成长曲线：聚合历史报告。不写入面试上下文，仅供复盘。"""
    from app.services.growth import build_growth_timeline

    sessions = db.scalars(
        select(InterviewSession)
        .where(
            InterviewSession.user_id == current_user.id,
            InterviewSession.status == "finished",
        )
        .order_by(InterviewSession.started_at.asc())
        .limit(50)
    ).all()
    if not sessions:
        return {
            "session_count": 0,
            "points": [],
            "comparisons": [],
            "recurring_gaps": [],
            "dimension_progress": [],
            "recency_dimensions": {},
            "skill_tags": [],
            "practice_suggestions": [
                {
                    "id": "default:full",
                    "kind": "default",
                    "title": "开始第一场独立全流程",
                    "reason": "主路径：完整模拟面试，不依赖历史记忆",
                    "interview_mode": "full",
                    "interview_type": "full",
                    "practice_focus": "",
                    "priority": 1,
                }
            ],
            "summary": {
                "first_overall": None,
                "latest_overall": None,
                "total_delta": None,
                "readiness": None,
                "primary_role": "",
                "trend": "insufficient",
            },
        }

    reports = {
        r.session_id: r
        for r in db.scalars(
            select(ScoreReport).where(
                ScoreReport.session_id.in_([s.id for s in sessions])
            )
        ).all()
    }
    rows = []
    for s in sessions:
        report_row = reports.get(s.id)
        if report_row is None:
            continue
        try:
            report = json.loads(report_row.report_json)
        except Exception:
            continue
        rows.append(
            {
                "session_id": s.id,
                "mode": s.interview_mode,
                "type": s.interview_type,
                "target_role": getattr(s, "target_role", "") or "",
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                "report": report,
            }
        )
    return build_growth_timeline(rows)


@router.post("/growth/insight")
def growth_insight(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """可选 AI 成长解读（当场生成，不推通知、不进面试记忆）。"""
    from app.services.growth import build_growth_insight, build_growth_timeline

    assert_platform_allowed(db, current_user)
    # 复用 get_growth 逻辑
    data = get_growth(current_user=current_user, db=db)
    if data.get("session_count", 0) < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="暂无报告可解读")
    try:
        insight = build_growth_insight(data)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="成长解读生成失败，请稍后重试"
        )
    return {"insight": insight}
