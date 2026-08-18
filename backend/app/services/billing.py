"""平台 Key 试用额度：按面试场次扣次，自填 Key 不扣。"""
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import QuotaGrant, User, UserLlmSetting

PLATFORM_KEY_EXHAUSTED = (
    "平台试用次数已用完，请在「模型设置」填写自己的 API Key，或联系管理员发放额度"
)


def admin_username_set() -> set[str]:
    return {n.strip() for n in settings.admin_usernames.split(",") if n.strip()}


def sync_admin_flag(user: User) -> bool:
    """若用户名在 ADMIN_USERNAMES 中，提升为管理员。返回是否变更。"""
    if user.username in admin_username_set() and not user.is_admin:
        user.is_admin = 1
        return True
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
    user.platform_quota = max(0, int(user.platform_quota or 0) - 1)
    db.add(
        QuotaGrant(
            admin_id=None,
            user_id=user.id,
            delta=-1,
            note=note,
        )
    )
    return int(user.platform_quota)


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
