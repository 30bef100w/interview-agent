from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserLlmSetting(Base):
    """用户的 LLM 配置：用自己的 key + 预置模型选项。"""

    __tablename__ = "user_llm_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), default="deepseek")  # deepseek|zhipu|qwen|doubao|siliconflow
    model: Mapped[str] = mapped_column(String(64), default="deepseek-chat")
    api_key_encrypted: Mapped[str] = mapped_column(String(512), default="")
    is_default: Mapped[int] = mapped_column(Integer, default=0)  # 1=使用系统默认 key（未配自己的）
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class LLMUsage(Base):
    """单次 LLM 调用用量：token + 换算金额，供用户查询防"盗用"疑虑。"""

    __tablename__ = "llm_usages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    used_platform_key: Mapped[int] = mapped_column(Integer, default=0)  # 1=走平台 Key
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
