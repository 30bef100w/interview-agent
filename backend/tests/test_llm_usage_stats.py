from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import InterviewSession, LLMUsage, Resume, User
from app.services.llm_usage_stats import summarize_user_usage


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_usage_groups_by_session_and_hides_other_users():
    db = _session()
    me = User(username="me", password_hash="x")
    other = User(username="other", password_hash="x")
    db.add_all([me, other])
    db.flush()

    my_resume = Resume(user_id=me.id, filename="a.pdf", raw_text="t")
    other_resume = Resume(user_id=other.id, filename="b.pdf", raw_text="t")
    db.add_all([my_resume, other_resume])
    db.flush()

    t0 = datetime.now(timezone.utc)
    mine_a = InterviewSession(
        user_id=me.id,
        resume_id=my_resume.id,
        interview_mode="full",
        interview_type="full",
        target_role="后端",
        target_company="深问",
        started_at=t0,
    )
    mine_b = InterviewSession(
        user_id=me.id,
        resume_id=my_resume.id,
        interview_mode="specialized",
        interview_type="ba_gu",
        started_at=t0 + timedelta(hours=1),
    )
    theirs = InterviewSession(
        user_id=other.id,
        resume_id=other_resume.id,
        interview_mode="full",
        interview_type="full",
        started_at=t0,
    )
    db.add_all([mine_a, mine_b, theirs])
    db.flush()

    db.add_all(
        [
            LLMUsage(
                user_id=me.id,
                session_id=mine_a.id,
                provider="deepseek",
                model="deepseek-chat",
                input_tokens=1000,
                output_tokens=200,
                cost_yuan=0.01,
                created_at=t0,
            ),
            LLMUsage(
                user_id=me.id,
                session_id=mine_a.id,
                provider="deepseek",
                model="deepseek-chat",
                input_tokens=500,
                output_tokens=100,
                cost_yuan=0.005,
                created_at=t0 + timedelta(minutes=5),
            ),
            LLMUsage(
                user_id=me.id,
                session_id=mine_b.id,
                provider="deepseek",
                model="deepseek-chat",
                input_tokens=100,
                output_tokens=20,
                cost_yuan=0.001,
                created_at=t0 + timedelta(hours=2),
            ),
            LLMUsage(
                user_id=other.id,
                session_id=theirs.id,
                provider="deepseek",
                model="deepseek-chat",
                input_tokens=99999,
                output_tokens=99999,
                cost_yuan=88.0,
                created_at=t0,
            ),
        ]
    )
    db.commit()

    data = summarize_user_usage(db, me.id)
    assert data["session_count"] == 2
    assert data["total_input_tokens"] == 1600
    assert data["total_output_tokens"] == 320
    assert data["total_cost_yuan"] == 0.016
    assert [row["session_id"] for row in data["recent"]] == [mine_b.id, mine_a.id]
    first = data["recent"][1]
    assert first["call_count"] == 2
    assert first["input_tokens"] == 1500
    assert first["output_tokens"] == 300
    assert first["cost_yuan"] == 0.015
    assert first["target_role"] == "后端"
    assert first["target_company"] == "深问"
    assert all(row["session_id"] != theirs.id for row in data["recent"])
    db.close()
