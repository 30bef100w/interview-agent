from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TagMismatchReview(Base):
    """题库标签错标审核：LLM 过滤剔除后入队，运维定期处理。"""

    __tablename__ = "tag_mismatch_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    lane: Mapped[str] = mapped_column(String(32), index=True)  # role_filter | scene_filter
    target_roles: Mapped[str] = mapped_column(Text, default="[]")
    question: Mapped[str] = mapped_column(String(512), default="")
    question_norm: Mapped[str] = mapped_column(String(512), default="", index=True)
    tagged_roles: Mapped[str] = mapped_column(Text, default="[]")
    tagged_scenes: Mapped[str] = mapped_column(Text, default="[]")
    company: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(32), default="")
    filter_reason: Mapped[str] = mapped_column(String(64), default="llm_rejected")
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    mq_message_id: Mapped[str] = mapped_column(String(128), default="")
    note: Mapped[str] = mapped_column(String(512), default="")
    resolved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
