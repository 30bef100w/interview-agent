from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512), default="")  # uploads 下相对文件名
    raw_text: Mapped[str] = mapped_column(Text, default="")
    profile_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class ResumeBulletNote(Base):
    """挂在简历某一条 bullet 下的复习材料：问答对或注释。"""

    __tablename__ = "resume_bullet_notes"
    __table_args__ = (
        Index("ix_resume_bullet_notes_lookup", "resume_id", "item_key", "bullet_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    section_type: Mapped[str] = mapped_column(String(16))  # project | experience
    item_key: Mapped[str] = mapped_column(String(32))
    bullet_key: Mapped[str] = mapped_column(String(32))
    item_label: Mapped[str] = mapped_column(String(256), default="")
    bullet_text: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(8))  # qa | note
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
