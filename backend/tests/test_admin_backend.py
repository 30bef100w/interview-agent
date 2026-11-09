"""运营接口契约与数据边界测试：隔离 SQLite，不访问真实数据或模型。"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.api import admin, observability
from app.config import settings
from app.db import Base, get_db
from app.models import (
    Answer, InterviewSession, LLMUsage, Question, QuotaGrant, Resume,
    SystemLog, TagMismatchReview, User, UserLlmSetting,
)
from app.services.auth_service import create_token
from app.services import admin_trace_service
from app.services.admin_service import AdminService, business_day_start


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "admin-tests-isolated-key-with-at-least-32-bytes")
    monkeypatch.setattr(admin_trace_service, "TRACE_ROOT", tmp_path / "logs")
    engine = create_engine(f"sqlite:///{tmp_path / 'admin.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        operator = User(username="operator", password_hash="hash-admin", is_admin=1)
        alice = User(username="alice", password_hash="hash-alice", platform_quota=3)
        bob = User(username="bob", password_hash="hash-bob", platform_quota=0)
        db.add_all([operator, alice, bob])
        db.flush()
        resume = Resume(user_id=alice.id, filename="test.pdf", raw_text="private resume text")
        db.add(resume)
        db.flush()
        sessions = [InterviewSession(user_id=alice.id, resume_id=resume.id, interview_mode="full",
            interview_type="full", status=status, target_role="backend", target_company="test",
            started_at=datetime(2026, 11, 5, 16, index), state_json='{"private": "state"}')
            for index, status in enumerate(["active", "finished"])]
        db.add_all(sessions)
        db.flush()
        first = Question(session_id=sessions[0].id, q_index=0, question_type="qa", text="first question")
        second = Question(session_id=sessions[0].id, q_index=1, question_type="qa", text="second question")
        db.add_all([first, second])
        db.flush()
        db.add(Answer(session_id=sessions[0].id, question_id=first.id, content="first answer"))
        db.add_all([
            LLMUsage(user_id=alice.id, session_id=sessions[0].id, provider="test", model="test-model",
                     used_platform_key=1, input_tokens=100, output_tokens=20, cost_yuan=0.15),
            LLMUsage(user_id=alice.id, session_id=sessions[0].id, provider="test", model="own-model",
                     used_platform_key=0, cost_yuan=0.20),
            UserLlmSetting(user_id=alice.id, api_key_encrypted="never-return-this-key", is_default=0),
            TagMismatchReview(question="q", question_norm="q", lane="role_filter", tagged_roles="invalid json"),
            SystemLog(level="error", source="engine", path="/api/interview", message="failure", user_id=alice.id),
            SystemLog(level="warning", source="worker", message="retry", user_id=bob.id),
        ])
        db.commit()
        tokens = {u.username: {"Authorization": f"Bearer {create_token(u.id, u.password_hash)}"} for u in (operator, alice, bob)}
        ids = SimpleNamespace(admin=operator.id, alice=alice.id, bob=bob.id,
                              session=sessions[0].id, other_session=sessions[1].id)
    app = FastAPI()
    app.include_router(admin.router)
    app.include_router(observability.router)
    def isolated_db():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = isolated_db
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, db=factory, engine=engine, headers=tokens,
                              ids=ids, root=tmp_path / "logs", app=app)
    engine.dispose()


def get(world, path, **params):
    return world.client.get(path, params=params, headers=world.headers["operator"])


def test_all_read_routes_require_admin_and_roles_are_rechecked(world):
    paths = ["/api/admin/stats", "/api/admin/analytics", "/api/admin/users", "/api/admin/logs", "/api/admin/usage/platform",
             "/api/admin/sessions", f"/api/admin/sessions/{world.ids.session}",
             f"/api/admin/sessions/{world.ids.session}/messages", f"/api/admin/sessions/{world.ids.session}/trace",
             "/api/admin/tag-mismatches", "/api/admin/tag-mismatches/stats", "/api/admin/question-bank/catalog",
             "/api/observability/metrics", f"/api/observability/sessions/{world.ids.session}/trace"]
    for path in paths:
        assert world.client.get(path).status_code == 401, path
        assert world.client.get(path, headers=world.headers["alice"]).status_code == 403, path
    with world.db() as db:
        db.get(User, world.ids.admin).is_admin = 0
        db.commit()
    assert get(world, "/api/admin/stats").status_code == 403


def test_all_admin_mutation_routes_require_admin(world):
    for route in admin.router.routes:
        for method in route.methods - {"GET", "HEAD", "OPTIONS"}:
            path = route.path.replace("{user_id}", str(world.ids.alice)).replace("{item_id}", "1")
            assert world.client.request(method, path, json={}).status_code == 401, path
            assert world.client.request(method, path, json={}, headers=world.headers["alice"]).status_code == 403, path


def test_users_page_preserves_fields_and_queries_do_not_grow_per_user(world):
    with world.db() as db:
        db.add_all(User(username=f"user-{i}", password_hash="x") for i in range(20))
        db.commit()
    statements = []
    def record(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(world.engine, "before_cursor_execute", record)
    try:
        res = get(world, "/api/admin/users", limit=200)
    finally:
        event.remove(world.engine, "before_cursor_execute", record)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] == 23 and len(data["items"]) == 23
    assert len(statements) <= 6  # auth + count + page + 三项批量汇总
    alice = next(row for row in data["items"] if row["id"] == world.ids.alice)
    assert alice["interview_count"] == 2
    assert alice["platform_cost_yuan"] == 0.15
    assert alice["has_own_key"] is True and alice["uses_platform_key"] is False
    assert "password_hash" not in res.text and "never-return-this-key" not in res.text
    assert get(world, "/api/admin/users", q="alice").json()["total"] == 1
    assert get(world, "/api/admin/users", q="%_").json()["total"] == 0
    assert get(world, "/api/admin/users", q="9" * 100).status_code == 200
    assert get(world, "/api/admin/users", limit=1, offset=23).json()["items"] == []


@pytest.mark.parametrize("path,params", [
    ("/api/admin/users", {"limit": 201}), ("/api/admin/users", {"offset": -1}),
    ("/api/admin/sessions", {"status": "invalid"}),
    ("/api/admin/sessions", {"start_time": "2026-11-07", "end_time": "2026-11-06"}),
    ("/api/admin/logs", {"start_time": "bad"}),
    ("/api/admin/sessions", {"user_id": 2**80}),
])
def test_invalid_queries_are_validation_errors(world, path, params):
    assert get(world, path, **params).status_code == 422


def test_sessions_filters_detail_messages_and_missing_rows(world):
    sid = world.ids.session
    data = get(world, "/api/admin/sessions", username="alice", status="active", mode="full",
               start_time="2026-11-06T00:00:00+08:00", end_time="2026-11-06T00:00:30+08:00").json()
    assert data["total"] == 1
    row = data["items"][0]
    assert row["id"] == sid and row["question_count"] == 2 and row["answer_count"] == 1
    assert row["llm_calls"] == 2 and row["cost_yuan"] == 0.35
    assert get(world, "/api/admin/sessions", user_id=world.ids.bob).json()["total"] == 0
    detail = get(world, f"/api/admin/sessions/{sid}")
    assert detail.status_code == 200 and detail.json()["report"] is None
    assert "private resume text" not in detail.text and '"private"' not in detail.text
    data = get(world, f"/api/admin/sessions/{sid}/messages", limit=2).json()
    assert data["total"] == 3
    assert [(row["role"], row["content"]) for row in data["items"]] == [
        ("assistant", "first question"), ("user", "first answer")]
    assert get(world, f"/api/admin/sessions/{sid}/messages", offset=2).json()["items"][0]["content"] == "second question"
    assert get(world, f"/api/admin/sessions/{sid}/messages", role="user").json()["total"] == 1
    for suffix in ("", "/messages", "/trace"):
        assert get(world, f"/api/admin/sessions/99999{suffix}").status_code == 404


def test_quota_and_audit_commit_together_and_reject_overdraw(world):
    path = f"/api/admin/users/{world.ids.alice}/quota"
    response = world.client.post(path, json={"delta": 2, "note": "test grant"}, headers=world.headers["operator"])
    assert response.status_code == 200 and response.json()["platform_quota"] == 5
    assert world.client.post(path, json={"delta": -6}, headers=world.headers["operator"]).status_code == 400
    assert world.client.post(path, json={"delta": 0}, headers=world.headers["operator"]).status_code == 400
    with world.db() as db:
        assert db.get(User, world.ids.alice).platform_quota == 5
        grants = db.scalars(select(QuotaGrant)).all()
        assert len(grants) == 1 and grants[0].delta == 2
        logs = db.scalars(select(SystemLog).where(SystemLog.source == "admin")).all()
        assert len(logs) == 1 and logs[0].user_id == world.ids.admin and logs[0].path == path


def test_failed_audit_rolls_back_quota_and_ledger(world):
    with world.db() as db:
        def fail_audit(session, context, instances):
            if any(isinstance(row, SystemLog) for row in session.new):
                raise RuntimeError("audit unavailable")
        event.listen(db, "before_flush", fail_audit)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            AdminService(db).grant_quota(world.ids.alice, SimpleNamespace(delta=10, note="test"), db.get(User, world.ids.admin))
        event.remove(db, "before_flush", fail_audit)
    with world.db() as db:
        assert db.get(User, world.ids.alice).platform_quota == 3
        assert db.scalar(select(func.count(QuotaGrant.id))) == 0


def test_user_mutations_and_audit_do_not_expose_password_or_key(world):
    base = f"/api/admin/users/{world.ids.alice}"
    response = world.client.patch(base, json={"is_disabled": True, "platform_quota": 8}, headers=world.headers["operator"])
    assert response.status_code == 200 and response.json()["platform_quota"] == 8
    assert world.client.post(base + "/clear-llm-key", headers=world.headers["operator"]).status_code == 200
    detail = get(world, base).json()
    assert detail["is_disabled"] and not detail["has_own_key"]
    assert detail["quota_grants"][0]["delta"] == 5
    for body in ({"is_disabled": True}, {"is_admin": False}):
        assert world.client.patch(f"/api/admin/users/{world.ids.admin}", json=body, headers=world.headers["operator"]).status_code == 400
    assert world.client.patch(base, json={"unknown_field": "x"}, headers=world.headers["operator"]).status_code == 422
    assert world.client.patch(base, json={}, headers=world.headers["operator"]).status_code == 400
    assert "never-return-this-key" not in get(world, "/api/admin/logs").text


def test_quota_deltas_use_current_database_balance(world):
    # 两个管理员均已读到旧余额，后提交者仍以数据库最新余额相加。
    from app.services.billing import grant_platform_quota
    with world.db() as a, world.db() as b:
        b.expire_on_commit = False
        stale = b.get(User, world.ids.alice)
        b.commit()
        user = a.get(User, world.ids.alice)
        grant_platform_quota(a, admin=a.get(User, world.ids.admin), user=user, delta=2)
        a.commit()
        assert stale.platform_quota == 3
        assert grant_platform_quota(b, admin=b.get(User, world.ids.admin), user=stale, delta=4) == 9
        b.commit()
    with world.db() as db:
        assert db.get(User, world.ids.alice).platform_quota == 9
        assert db.scalar(select(func.sum(QuotaGrant.delta))) == 6


def test_logs_and_platform_cost_share_filters_and_pagination(world):
    logs = get(world, "/api/admin/logs", level="error", source="engine", user_id=world.ids.alice, q="failure").json()
    assert logs["total"] == 1 and logs["items"][0]["level"] == "error"
    assert get(world, "/api/admin/logs", source="engine", offset=1).json()["items"] == []
    usage = get(world, "/api/admin/usage/platform", session_id=world.ids.session, limit=1).json()
    assert usage["total"] == 1 and usage["total_cost_yuan"] == 0.15
    assert get(world, "/api/admin/usage/platform", model="own-model").json()["total_cost_yuan"] == 0


def test_beijing_day_and_month_boundaries(world, monkeypatch):
    from app.services import admin_service
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 1, 0, 30, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(admin_service, "datetime", FixedDateTime)
    assert business_day_start(datetime(2026, 11, 1, 0, 30, tzinfo=timezone.utc)) == datetime(2026, 10, 31, 16)
    with world.db() as db:
        db.get(User, world.ids.alice).last_active_at = datetime(2026, 10, 31, 17)
        for answer in db.scalars(select(Answer)):
            answer.created_at = datetime(2026, 10, 31, 18)
        for row in db.scalars(select(InterviewSession)):
            row.started_at = datetime(2026, 10, 31, 17)
        db.commit()
    data = get(world, "/api/admin/stats").json()
    assert data["dau"] == 1 and data["interviews_today"] == 2 and data["interviews_month"] == 2
    assert data["timezone"] == "Asia/Shanghai"


def test_analytics_accepts_numeric_days_and_limits_ranges(world):
    response = get(world, "/api/admin/analytics", days=30)
    assert response.status_code == 200, response.text
    assert len(response.json()["trend"]) == 30
    for params in ({"days": 91}, {"start_date": "2026-11-08", "end_date": "2026-11-01"},
                   {"end_date": "2999-01-01"}):
        assert get(world, "/api/admin/analytics", **params).status_code == 422


def test_test_account_flag_is_audited_and_filters_apply_to_details(world):
    path = f"/api/admin/users/{world.ids.alice}"
    response = world.client.patch(path, json={"is_test": True}, headers=world.headers["operator"])
    assert response.status_code == 200 and response.json()["is_test"]
    assert get(world, "/api/admin/sessions", business_only=True).json()["total"] == 0
    assert get(world, "/api/admin/usage/platform", business_only=True).json()["total"] == 0
    assert get(world, "/api/admin/sessions").json()["total"] == 2
    assert any("is_test=1" in row["message"] for row in get(world, "/api/admin/logs", source="admin").json()["items"])


def test_exclusive_detail_boundary_and_provider(world):
    end = "2026-11-06T00:01:00+08:00"
    assert get(world, "/api/admin/sessions", end_time=end, end_exclusive=True).json()["total"] == 1
    assert get(world, "/api/admin/sessions", end_time=end).json()["total"] == 2
    assert get(world, "/api/admin/usage/platform", provider="missing").json()["total"] == 0


def test_review_keeps_contract_and_audits_resolution(world):
    data = get(world, "/api/admin/tag-mismatches").json()
    assert data["total"] == 1 and data["items"][0]["tagged_roles"] == []
    item = data["items"][0]["id"]
    response = world.client.post(f"/api/admin/tag-mismatches/{item}/resolve",
        json={"status": "dismissed", "note": "checked"}, headers=world.headers["operator"])
    assert response.status_code == 200 and response.json()["resolved_by"] == world.ids.admin
    assert get(world, "/api/admin/tag-mismatches/stats").json()["pending"] == 0
    assert get(world, "/api/admin/tag-mismatches", status="dismissed").json()["total"] == 1
    assert get(world, "/api/admin/tag-mismatches/9999/question").status_code == 404


def test_trace_handles_partial_files_and_both_entrypoints_match(world):
    sid = world.ids.session
    for name in ("engine_trace", "create_trace", "session_guard"):
        (world.root / name).mkdir(parents=True, exist_ok=True)
    (world.root / "create_trace" / f"{sid}.json").write_text('{"steps":[null,{"step":"plan","at":"2026-11-06T08:00:00+08:00","duration_s":"bad"}]}')
    (world.root / "engine_trace" / f"{sid}.jsonl").write_text(
        'null\n[]\n' + json.dumps({"node": "engine", "ts": "2026-11-06T00:00:01Z"}) + '\n{"incomplete":')
    (world.root / "session_guard" / f"{sid}.jsonl").write_text(json.dumps({"event": "guard", "ts": "bad"}))
    data = get(world, f"/api/admin/sessions/{sid}/trace").json()
    assert [row["node"] for row in data["timeline"]] == ["plan", "engine", "guard"]
    assert data == get(world, f"/api/observability/sessions/{sid}/trace").json()


def test_review_apply_uses_editor_and_updates_audit_in_isolation(world, tmp_path, monkeypatch):
    from app.services import admin_review_service as reviews
    editor = reviews.editor
    path = tmp_path / "questions.jsonl"
    path.write_text(json.dumps({"question": "q", "roles": ["old"], "category": "bagu"}) + "\n")
    monkeypatch.setattr(editor, "QUESTIONS_PATH", path)
    monkeypatch.setattr(editor, "KB", tmp_path)
    monkeypatch.setattr(editor, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(editor, "invalidate_question_cache", lambda: None)
    monkeypatch.setattr(reviews, "all_roles", lambda: {"backend": {"name": "后端"}})
    monkeypatch.setattr(reviews, "load_companies", lambda: {"companies": []})
    monkeypatch.setattr(editor, "load_scene_catalog", lambda: {"business_scenes": [], "tech_scenes": []})
    response = world.client.post("/api/admin/tag-mismatches/1/apply", json={
        "action": "update", "roles": ["backend"], "category": "project",
    }, headers=world.headers["operator"])
    assert response.status_code == 200, response.text
    assert response.json()["review"]["status"] == "resolved"
    assert json.loads(path.read_text())["roles"] == ["backend"]
    assert get(world, "/api/admin/tag-mismatches/1/question").json()["category"] == "project"
    assert get(world, "/api/admin/logs", source="admin").json()["total"] == 1
    assert list((tmp_path / "backups").glob("*.jsonl"))


def test_no_duplicate_method_paths(world):
    seen = set()
    for route in world.app.routes:
        for method in getattr(route, "methods", []):
            key = method, route.path
            assert key not in seen, key
            seen.add(key)
