from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Answer, InterviewSession, LLMUsage, Question, Resume, ScoreReport, User
from app.schemas.admin import AnalyticsQuery
from app.services.admin_analytics_service import AdminAnalyticsService, comparison

NOW = datetime(2026, 11, 9, 2, tzinfo=timezone.utc)
START = datetime(2026, 11, 1, 16)  # 北京时间 11 月 2 日 00:00
END = datetime(2026, 11, 8, 16)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def user(db, name="user", **kw):
    row = User(username=name, password_hash="hash", created_at=START, **kw)
    db.add(row)
    db.flush()
    return row


def interview(db, owner, at=START, *, status="active", finished=None, kind="full"):
    resume = Resume(user_id=owner.id, filename="test.pdf")
    db.add(resume)
    db.flush()
    row = InterviewSession(user_id=owner.id, resume_id=resume.id, interview_mode="full",
                           interview_type=kind, status=status, started_at=at, finished_at=finished)
    db.add(row)
    db.flush()
    return row


def answer(db, session, at):
    question = Question(session_id=session.id, q_index=0, question_type="qa", text="q")
    db.add(question)
    db.flush()
    db.add(Answer(session_id=session.id, question_id=question.id, content="answer", created_at=at))
    db.flush()


def usage(db, owner, session, at, cost, *, platform=1, provider="one"):
    db.add(LLMUsage(user_id=owner.id, session_id=session.id if session else None,
        provider=provider, model="model", used_platform_key=platform, created_at=at,
        cost_yuan=cost, input_tokens=10, output_tokens=2))
    db.flush()


def overview(db, days=7):
    return AdminAnalyticsService(db).overview(AnalyticsQuery(days=days), now=NOW)


def values(data):
    return {item["key"]: item["current"] for item in data["metrics"]}


def test_empty_data_keeps_zero_distinct_from_unknown(db):
    data = overview(db)
    assert values(data) == {"new_users": 0, "answer_users": 0, "answered_sessions": 0,
                           "completion_rate": None, "report_rate": None, "cost_per_session": None}
    assert len(data["trend"]) == len(data["previous_trend"]) == 7
    assert data["trend"][0]["date"] == "2026-11-02"
    assert data["period"]["previous_end_date"] == "2026-11-01"
    assert all(step["count"] == 0 for step in data["funnel"])
    assert all(item["rate"] is None for item in data["retention"])


def test_no_join_multiplication_excludes_staff_and_test_but_keeps_disabled(db):
    owner = user(db, is_disabled=1)
    session = interview(db, owner, status="finished", finished=START + timedelta(hours=2))
    answer(db, session, START + timedelta(minutes=30))
    answer(db, session, START + timedelta(hours=1))
    db.add(ScoreReport(session_id=session.id, report_json="{}", generation_status="success",
                       created_at=START + timedelta(hours=2)))
    usage(db, owner, session, START, .1)
    usage(db, owner, session, START + timedelta(hours=1), .2)
    usage(db, owner, session, START + timedelta(hours=1), .4, provider="two")
    usage(db, owner, session, START, 8, platform=0)
    for name, flag in (("admin", {"is_admin": 1}), ("test", {"is_test": 1})):
        excluded = user(db, name, **flag)
        other = interview(db, excluded)
        answer(db, other, START)
        usage(db, excluded, other, START, 99)
    data = overview(db)
    assert values(data) == {"new_users": 1, "answer_users": 1, "answered_sessions": 1,
                           "completion_rate": 1, "report_rate": 1, "cost_per_session": .7}
    assert data["cost"]["total_yuan"] == .7
    assert len(data["cost"]["models"]) == 2
    assert data["cost"]["models"][1]["records"] == 2
    assert [step["count"] for step in data["funnel"]] == [1, 1, 1, 1]
    assert data["quality"]["cost_recorded_sessions"] == 1


@pytest.mark.parametrize("report_status,expected", [("success", 1), ("fallback", 0), ("unknown", None)])
def test_completion_and_report_results_are_separate_and_pending_is_excluded(db, report_status, expected):
    owner = user(db)
    session = interview(db, owner, status="finished", finished=START + timedelta(hours=2))
    answer(db, session, START + timedelta(hours=1))
    db.add(ScoreReport(session_id=session.id, report_json="{}", generation_status=report_status,
                       created_at=START + timedelta(hours=2)))
    interview(db, owner, END - timedelta(hours=1), status="failed")  # 到 NOW 未满 24 小时
    late = interview(db, owner, START + timedelta(days=1), status="finished",
                     finished=START + timedelta(days=2, hours=1))
    answer(db, late, START + timedelta(days=2, hours=1))
    data = overview(db)
    assert data["quality"]["mature"] == 2 and data["quality"]["pending"] == 1
    assert values(data)["completion_rate"] == .5
    assert values(data)["report_rate"] == expected
    assert data["types"][0]["failed"] == 1
    assert [step["count"] for step in data["funnel"]] == [2, 1, 1, int(report_status == "success")]


def test_activity_uses_answer_time_and_exclusive_beijing_boundary(db):
    owner = user(db)
    session = interview(db, owner, START - timedelta(days=1))
    answer(db, session, START - timedelta(microseconds=1))
    answer(db, session, START)
    answer(db, session, END)
    data = overview(db)
    assert data["quality"]["created"] == 0
    assert values(data)["answer_users"] == values(data)["answered_sessions"] == 1
    assert data["trend"][0]["answer_users"] == 1
    assert data["trend"][-1]["answer_users"] == 0
    # 只有登录、从未答题的人不算活跃。
    user(db, "login-only", last_active_at=START)
    assert values(overview(db))["answer_users"] == 1


def test_cost_compares_same_24h_window_and_separates_period_from_cohort(db):
    owner = user(db)
    current = interview(db, owner, END - timedelta(hours=16))
    previous = interview(db, owner, START - timedelta(hours=16))
    # 每场的首 24h 跨出其创建周期；两个会话均已成熟。
    usage(db, owner, current, END + timedelta(hours=2), .3)
    usage(db, owner, previous, START + timedelta(hours=2), .1)
    usage(db, owner, current, END + timedelta(hours=9), 9)  # 超出该场首 24h
    usage(db, owner, None, START, .05)
    data = overview(db)
    metric = next(row for row in data["metrics"] if row["key"] == "cost_per_session")
    assert metric["current"] == .3 and metric["previous"] == .1
    assert metric["change"]["value"] == 200
    assert data["cost"]["total_yuan"] == .15
    assert data["cost"]["unassigned_yuan"] == .05


def test_answer_retention_is_first_ever_answer_and_complete_natural_day(db):
    first = user(db, "first")
    first_session = interview(db, first, START - timedelta(days=1))
    first_at = START - timedelta(days=1) + timedelta(hours=3)  # 北京 11/1
    answer(db, first_session, first_at)
    answer(db, first_session, first_at + timedelta(days=1))
    answer(db, first_session, first_at + timedelta(days=7))
    second = user(db, "second")
    second_session = interview(db, second)
    answer(db, second_session, START + timedelta(hours=3))  # 北京 11/2，D7 是今天
    data = overview(db, days=30)
    d1, d7 = data["retention"]
    assert (d1["eligible"], d1["retained"], d1["rate"]) == (2, 1, .5)
    assert (d7["eligible"], d7["retained"], d7["pending"], d7["rate"]) == (1, 1, 1, 1)
    assert overview(db)["retention"][0]["eligible"] == 1  # 首次发生在区间前的不重新入群


@pytest.mark.parametrize("current,previous,unit,kind,value", [
    (0, 10, "count", "percent", -100), (0, 0, "count", "unchanged", 0),
    (5, 0, "count", "new", None), (.6, .5, "ratio", "pp", 10),
    (None, 1, "ratio", "unavailable", None),
])
def test_comparison_zero_null_and_percentage_points(current, previous, unit, kind, value):
    assert comparison(current, previous, unit) == {"kind": kind, "value": value}


def test_json_parse_retry_counts_each_attempt_once(monkeypatch):
    from app.observability.metrics import MetricsRegistry
    from app.services.llm import client as module
    registry = MetricsRegistry()
    monkeypatch.setattr(module, "metrics_registry", registry)
    replies = iter(["not json", '{"ok": true}'])
    def create(**kw):
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    llm = module.OpenAiLlm(client=fake, model="test")
    monkeypatch.setattr(llm, "_on_llm_error", lambda exc: None)
    assert llm.chat_json("s", "u") == {"ok": True}
    assert registry.snapshot()["llm"] == {"calls": 2, "errors": 1}
    assert registry.snapshot()["nodes"]["llm:test"]["count"] == 2


@pytest.mark.parametrize("fail,expected", [(False, "success"), (True, "fallback")])
def test_report_result_is_engine_owned_and_persisted(db, fail, expected):
    from app.services.interviewer_engine.report import ReportMixin
    from app.api.interview import _close_with_report
    class Engine(ReportMixin):
        def _report_user(self, state):
            return "report"
        def _sanitize_report(self, state, report):
            return report
    def reply(*args):
        if fail:
            raise ValueError("bad model output")
        return {"generation_status": "fallback", "summary": "ok"}  # 忽略模型声称的状态
    engine = Engine()
    engine.llm = SimpleNamespace(chat_json=reply)
    owner = user(db)
    session = interview(db, owner)
    state = SimpleNamespace(stage="SUMMARIZING", session_id=None)
    _close_with_report(session, db, state, engine)
    db.flush()
    report = db.query(ScoreReport).one()
    assert report.generation_status == expected
    assert session.status == "finished"


def test_old_schema_upgrade_preserves_rows_and_is_repeatable(monkeypatch):
    from sqlalchemy import inspect, text
    from app import db_migrate
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64), password_hash VARCHAR(128), created_at TIMESTAMP)"))
        conn.execute(text("CREATE TABLE score_reports (id INTEGER PRIMARY KEY, session_id INTEGER, report_json TEXT, created_at TIMESTAMP)"))
        conn.execute(text("INSERT INTO users (id, username) VALUES (1, 'existing')"))
        conn.execute(text("INSERT INTO score_reports (id, session_id, report_json) VALUES (1, 1, '{}')"))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_migrate, "engine", engine)
    db_migrate.ensure_schema()
    db_migrate.ensure_schema()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT username, is_test FROM users")).one() == ("existing", 0)
        assert conn.execute(text("SELECT generation_status FROM score_reports")).scalar_one() == "unknown"
    assert "ix_answers_created_at" in {index["name"] for index in inspect(engine).get_indexes("answers")}
    engine.dispose()


def test_outer_finish_exception_persists_fallback_instead_of_success(db):
    from app.api.interview import _close_with_report
    def fail(state):
        raise RuntimeError("finish failed")
    engine = SimpleNamespace(finish_interview=fail, _sanitize_report=lambda state, report: report)
    owner = user(db)
    session = interview(db, owner)
    _close_with_report(session, db, SimpleNamespace(stage="SUMMARIZING"), engine)
    db.flush()
    assert db.query(ScoreReport).one().generation_status == "fallback"
