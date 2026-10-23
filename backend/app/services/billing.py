"""平台 Key 试用额度：按面试场次扣次，自填 Key 不扣。"""
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import InterviewSession, QuotaGrant, User, UserLlmSetting

PLATFORM_KEY_EXHAUSTED = (
    "平台试用次数已用完，请在「模型设置」填写自己的 API Key，或联系管理员发放额度"
)


def admin_username_set() -> set[str]:
    return {n.strip() for n in settings.admin_usernames.split(",") if n.strip()}


def sync_admin_flag(user: User) -> bool:
    """Compatibility shim: roles are managed explicitly, never inferred from a name."""
    return False


def touch_active(user: User) -> None:
    user.last_active_at = datetime.now(timezone.utc)


def uses_platform_key(db: Session, user_id: int) -> bool:
    setting = db.scalars(
        select(UserLlmSetting).where(UserLlmSetting.user_id == user_id)
    ).first()
    if setting is None:
        return True
    if setting.is_default or not (setting.api_key_encrypted or "").strip():
        return True
    return False


def assert_platform_allowed(db: Session, user: User) -> None:
    """走平台 Key 且额度为 0 时拒绝。"""
    if uses_platform_key(db, user.id) and int(user.platform_quota or 0) <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PLATFORM_KEY_EXHAUSTED,
        )


def deduct_platform_quota(
    db: Session, user: User, *, note: str = "创建面试扣次"
) -> int:
    """创建面试成功后扣 1 次，写审计。返回剩余额度。"""
    result = db.execute(update(User).where(User.id == user.id, User.platform_quota > 0)
                        .values(platform_quota=User.platform_quota - 1)
                        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(status_code=403, detail=PLATFORM_KEY_EXHAUSTED)
    db.refresh(user)
    db.add(
        QuotaGrant(
            admin_id=None,
            user_id=user.id,
            delta=-1,
            note=note,
        )
    )
    return int(user.platform_quota)


def reserve_session_quota(db: Session, user: User, session: InterviewSession) -> None:
    """Reserve in the same transaction as session creation; never charge again on answer."""
    if uses_platform_key(db, user.id):
        deduct_platform_quota(db, user, note="创建面试预占次数，规划失败自动退回")
        session.billing_source = "platform"
        session.quota_state = "reserved"
    else:
        session.billing_source = "user"
        session.quota_state = "none"


def refund_session_quota(db: Session, session_id: int) -> bool:
    """CAS ensures concurrent failure handlers cannot refund twice. Caller commits."""
    user_id = db.scalar(select(InterviewSession.user_id).where(InterviewSession.id == session_id))
    refunded = db.execute(update(InterviewSession).where(
        InterviewSession.id == session_id, InterviewSession.quota_state == "reserved",
    ).values(quota_state="refunded", version=InterviewSession.version + 1)
      .execution_options(synchronize_session=False))
    if refunded.rowcount != 1:
        return False
    db.execute(update(User).where(User.id == user_id)
               .values(platform_quota=User.platform_quota + 1)
               .execution_options(synchronize_session=False))
    db.add(QuotaGrant(admin_id=None, user_id=user_id, delta=1, note=f"面试 {session_id} 规划失败退回预占"))
    return True


def grant_platform_quota(
    db: Session, *, admin: User, user: User, delta: int, note: str = ""
) -> int:
    if delta == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="delta 不能为 0"
        )
    user.platform_quota = max(0, int(user.platform_quota or 0) + int(delta))
    db.add(
        QuotaGrant(
            admin_id=admin.id,
            user_id=user.id,
            delta=int(delta),
            note=(note or "").strip()[:256],
        )
    )
    return int(user.platform_quota)
