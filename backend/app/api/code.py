"""算法题 API：运行（示例自测）与提交（完整判题 + AI 评审 + 状态机推进）。"""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.interview import _engine_for, _get_owned_session, _load_state, _save_state
from app.db import get_db
from app.models import Answer, CodeSubmission, InterviewSession, Question, User
from app.prompts.interview import ALGO_REVIEW_SYSTEM
from app.schemas.api import CodeRunRequest, CodeRunResponse, CodeSubmitRequest, CodeSubmitResponse
from app.services.code_judger import judge as judge_code
from app.services.code_judger import run_examples
from app.services.question_bank import build_problem_view

router = APIRouter(prefix="/api/interview", tags=["code"])


def _current_coding(session: InterviewSession) -> dict:
    """当前题若是算法题，返回 slug + 题面视图；否则 None。"""
    state = _load_state(session)
    if state.stage != "ASKING" or state.cursor >= len(state.plan):
        return None
    q = state.plan[state.cursor]
    if q["type"] != "coding":
        return None
    view = build_problem_view(q.get("slug", ""))
    if view is None:
        return None
    return view


def _check_coding_turn(session: InterviewSession, slug: str) -> None:
    if session.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="面试已结束")
    state = _load_state(session)
    if state.stage != "ASKING":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前不是算法题环节")
    q = state.plan[state.cursor]
    if q["type"] != "coding" or q.get("slug") != slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前题目不是 {slug}，请按页面提示作答",
        )


@router.post("/session/{session_id}/code/run", response_model=CodeRunResponse)
def run_code_examples(
    session_id: int,
    payload: CodeRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CodeRunResponse:
    session = _get_owned_session(db, session_id, current_user.id)
    _check_coding_turn(session, payload.slug)
    problem = build_problem_view(payload.slug)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    from app.services.code_judger import get_problem

    cfg = get_problem(payload.slug) or {
        "examples": problem["examples"],
        "method": problem["method"],
        "params": problem["params"],
    }
    result = run_examples(
        payload.code, cfg, language=payload.language, coding_mode=payload.coding_mode
    )
    return CodeRunResponse(slug=payload.slug, **{k: result[k] for k in ("verdict", "passed", "total", "results", "message") if k in result})


@router.post("/session/{session_id}/code/submit", response_model=CodeSubmitResponse)
def submit_code(
    session_id: int,
    payload: CodeSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CodeSubmitResponse:
    session = _get_owned_session(db, session_id, current_user.id)
    _check_coding_turn(session, payload.slug)
    problem = build_problem_view(payload.slug)
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")

    result = judge_code(
        payload.code, payload.slug, language=payload.language, coding_mode=payload.coding_mode
    )

    engine = _engine_for(db, current_user, session.id)
    review = engine.llm.chat_json(
        ALGO_REVIEW_SYSTEM,
        (
            f"【题目】\n{problem['title']}（{problem['difficulty']}）\n"
            f"{problem['description']}\n\n"
            f"【候选人代码】\n{payload.code[:3000]}\n\n"
            f"【判题结果】\n{json.dumps(result, ensure_ascii=False)[:4000]}"
        ),
    )
    score = max(1.0, min(10.0, float(review.get("score", 5))))
    review = {**review, "score": score}

    state = _load_state(session)
    state, message = engine.handle_coding(state, result["final"], score, review)

    # 写库：Question（coding）→ Answer → CodeSubmission
    q = state.plan[state.cursor - 1]
    qrow = db.scalars(
        select(Question).where(
            Question.session_id == session.id, Question.q_index == state.cursor - 1
        )
    ).first()
    if qrow is None:
        qrow = Question(
            session_id=session.id,
            q_index=state.cursor - 1,
            question_type="coding",
            text=q["text"],
            rubric_json=json.dumps({"slug": q.get("slug"), "difficulty": q.get("topic")}, ensure_ascii=False),
        )
        db.add(qrow)
        db.flush()
    db.add(
        Answer(
            session_id=session.id,
            question_id=qrow.id,
            content=f"[算法题提交] 判定：{result['final']}",
            score_json=json.dumps({"score": score}, ensure_ascii=False),
        )
    )
    db.add(
        CodeSubmission(
            session_id=session.id,
            question_id=qrow.id,
            code=payload.code,
            language=f"{payload.language}:{payload.coding_mode}",
            judge_result_json=json.dumps(result, ensure_ascii=False),
        )
    )
    _save_state(session, state)
    db.commit()

    return CodeSubmitResponse(
        judge=result,
        review=review,
        message=message,
        stage=state.stage,
        status=session.status,
        finished=session.status == "finished",
    )
