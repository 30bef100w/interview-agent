from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models import InterviewSession, User, UserFeedback
from app.schemas.feedback import FeedbackCreate, FeedbackOut
from app.services.feishu_notify import send_feishu_text

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

_CATEGORY_LABEL = {
    "bug": "Bug",
    "ux": "体验建议",
    "feature": "功能想要",
    "other": "其他",
}

_SOURCE_LABEL = {
    "contact": "联系我们",
    "second_session": "第二场邀评",
}


@router.post("", response_model=FeedbackOut)
def submit_feedback(
    payload: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    row = UserFeedback(
        user_id=current_user.id,
        source=payload.source,
        category=payload.category.strip(),
        content=payload.content.strip(),
        contact=(payload.contact or "").strip(),
        page_url=(payload.page_url or "").strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    cat = _CATEGORY_LABEL.get(row.category, row.category)
    src = _SOURCE_LABEL.get(row.source, row.source)
    lines = [
        f"用户：{current_user.username} (id={current_user.id})",
        f"来源：{src}",
        f"类型：{cat}",
        f"内容：{row.content[:1500]}",
    ]
    if row.contact:
        lines.append(f"回访联系方式：{row.contact}")
    if row.page_url:
        lines.append(f"页面：{row.page_url}")
    send_feishu_text("用户意见反馈", "\n".join(lines))

    return FeedbackOut(id=row.id)


@router.get("/finished-count")
def finished_session_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """已完成面试场次数，供第二场后邀评弹框判断。"""
    count = db.scalar(
        select(func.count())
        .select_from(InterviewSession)
        .where(
            InterviewSession.user_id == current_user.id,
            InterviewSession.status == "finished",
        )
    )
    return {"finished_count": int(count or 0)}
