from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    is_admin: Mapped[int] = mapped_column(Integer, default=0)  # 1=管理员
    is_disabled: Mapped[int] = mapped_column(Integer, default=0)  # 1=禁用，禁止登录
    platform_quota: Mapped[int] = mapped_column(Integer, default=3)  # 平台 Key 面试剩余次数
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
