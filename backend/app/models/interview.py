from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"))
    interview_mode: Mapped[str] = mapped_column(String(16))  # full | specialized
    interview_type: Mapped[str] = mapped_column(String(16))  # full | ba_gu | project | hr
    stages: Mapped[str] = mapped_column(Text, default="[]")  # 全流程阶段顺序 JSON
    status: Mapped[str] = mapped_column(String(16), default="CREATED")
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_q_index: Mapped[int] = mapped_column(Integer, default=0)
    question_count: Mapped[int] = mapped_column(Integer, default=8)  # 总轮次上限
    rounds_used: Mapped[int] = mapped_column(Integer, default=0)
    state_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # InterviewState 全量持久化
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parent_session_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 二期多轮面试预留
    # 目标岗位 / 企业：本场定向，规划与提问会消费
    target_role: Mapped[str] = mapped_column(String(128), default="")
    target_company: Mapped[str] = mapped_column(String(128), default="")
    billing_source: Mapped[str] = mapped_column(String(16), default="legacy", server_default="legacy")
    quota_state: Mapped[str] = mapped_column(String(16), default="none", server_default="none")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    pending_operation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation_deadline: Mapped[float | None] = mapped_column(Float, nullable=True)
    creation_deadline: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_submission_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __mapper_args__ = {"version_id_col": version}


class InterviewOperation(Base):
    """Durable cross-transport submission claim and replayable acknowledgement."""
    __tablename__ = "interview_operations"
    __table_args__ = (UniqueConstraint("session_id", "request_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="processing")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    q_index: Mapped[int] = mapped_column(Integer)
    question_type: Mapped[str] = mapped_column(String(16))  # qa | coding
    coding_question_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    rubric_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0)


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    content: Mapped[str] = mapped_column(Text)
    score_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class ScoreReport(Base):
    __tablename__ = "score_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("interview_sessions.id"), unique=True, index=True
    )
    report_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class CodeSubmission(Base):
    __tablename__ = "code_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    code: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16), default="python")
    judge_result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
