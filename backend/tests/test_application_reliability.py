"""Application boundaries: no production data, model calls or external notifications."""
import json
import threading
import time

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.config import settings
from app.db import Base, get_db
from app.models import InterviewOperation, InterviewSession, QuotaGrant, Resume, User, UserLlmSetting
from app.schemas.api import AnswerRequest, CreateSessionRequest
from app.schemas.auth import RegisterRequest
from app.schemas.interview import InterviewState
from app.services.auth_service import create_token, hash_password


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "isolated-test-signing-key-at-least-32-bytes")
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", connect_args={"check_same_thread": False},
                           poolclass=QueuePool, pool_size=1, max_overflow=0, pool_timeout=0.2)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        user = User(username="alice", password_hash="test-hash", platform_quota=1)
        db.add(user)
        db.flush()
        resume = Resume(user_id=user.id, filename="test.pdf", raw_text="test")
        db.add(resume)
        db.flush()
        session = InterviewSession(user_id=user.id, resume_id=resume.id, interview_mode="full",
                                   interview_type="full", status="active", state_json=json.dumps(InterviewState(session_id=1, resume_raw="test", profile={}).to_dict()))
        db.add(session)
        db.commit()
        ids = user.id, resume.id, session.id
        token = create_token(user.id, user.password_hash)
    yield factory, engine, ids, token
    engine.dispose()


def client_for(world, monkeypatch):
    from app.api import auth, interview_ws
    factory, _, _, _ = world
    monkeypatch.setattr(interview_ws, "SessionLocal", factory)
    monkeypatch.setattr(interview_ws, "load_checkpoint", lambda _: None)
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(interview_ws.router)
    def db_override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    return TestClient(app)


def test_password_change_revokes_http_and_ws(world, monkeypatch):
    client = client_for(world, monkeypatch)
    factory, _, (uid, _, sid), token = world
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    with factory() as db:
        db.get(User, uid).password_hash = "new-test-hash"
        db.commit()
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    with client.websocket_connect(f"/ws/interview/{sid}?token={token}") as ws:
        assert ws.receive_json()["status"] == 401


def test_legacy_token_without_password_version_is_rejected(world, monkeypatch):
    token = jwt.encode({"sub": "1", "exp": int(time.time()) + 60}, settings.jwt_secret,
                       algorithm=settings.jwt_algorithm)
    client = client_for(world, monkeypatch)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_reserved_name_cannot_register_or_repromote(world, monkeypatch):
    client = client_for(world, monkeypatch)
    monkeypatch.setattr(settings, "admin_usernames", "alice,bootstrap")
    assert client.post("/api/auth/register", json={"username": "bootstrap", "password": "safe-password"}).status_code == 409
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {world[3]}"})
    assert res.status_code == 200
    assert res.json()["is_admin"] is False


@pytest.mark.parametrize("password", ["x" * 73, "密" * 25, "🔒" * 19])
def test_password_byte_limit_is_validation_error(password):
    with pytest.raises(ValidationError):
        RegisterRequest(username="alice", password=password)
    from app.api.admin import ResetPasswordBody
    with pytest.raises(ValidationError):
        ResetPasswordBody(new_password=password)


def test_ws_releases_idle_db_connection_and_validates_messages(world, monkeypatch):
    from app.api import interview_ws
    client = client_for(world, monkeypatch)
    factory, engine, (uid, _, sid), token = world
    sent = []
    async def stream(*args):
        sent.append(args[-1])
    monkeypatch.setattr(interview_ws, "_stream_answer", stream)
    with client.websocket_connect(f"/ws/interview/{sid}?token={token}") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        assert engine.pool.checkedout() == 0
        with factory() as db:
            assert db.get(User, uid)
        for value in [[], None, {"type": "answer", "text": "a" * 2001}, {"type": "answer", "text": 123}, {"type": "answer", "text": "   "}]:
            ws.send_json(value)
            assert ws.receive_json()["type"] == "error"
        assert not sent
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
        assert engine.pool.checkedout() == 0


def test_disabled_account_cannot_connect_or_keep_using_ws(world, monkeypatch):
    client = client_for(world, monkeypatch)
    factory, _, (uid, _, sid), token = world
    with client.websocket_connect(f"/ws/interview/{sid}?token={token}") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        with factory() as db:
            db.get(User, uid).is_disabled = 1
            db.commit()
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["status"] == 403
    with client.websocket_connect(f"/ws/interview/{sid}?token={token}") as ws:
        assert ws.receive_json()["status"] == 403


def test_quota_reservation_is_atomic_and_refund_is_once(world):
    from app.services.billing import reserve_session_quota, refund_session_quota
    factory, _, (uid, rid, _), _ = world
    with factory() as db:
        user = db.get(User, uid)
        first = InterviewSession(user_id=uid, resume_id=rid, interview_mode="full", interview_type="full", status="creating")
        reserve_session_quota(db, user, first)
        db.add(first)
        db.commit()
        sid = first.id
        assert user.platform_quota == 0
        with pytest.raises(HTTPException) as err:
            reserve_session_quota(db, user, InterviewSession())
        assert err.value.status_code == 403
        db.rollback()
        assert refund_session_quota(db, sid) is True
        db.commit()
        assert refund_session_quota(db, sid) is False
        db.commit()
        assert db.get(User, uid, populate_existing=True).platform_quota == 1
        assert [g.delta for g in db.scalars(select(QuotaGrant).order_by(QuotaGrant.id))] == [-1, 1]


def test_last_quota_can_create_and_continue_without_double_charge(world, monkeypatch):
    from fastapi import BackgroundTasks
    from app.api import interview as api
    factory, _, (uid, rid, _), _ = world
    monkeypatch.setattr(api, "trace_begin", lambda *a, **kw: None)
    monkeypatch.setattr(api, "trace_finish", lambda *a, **kw: None)
    class FakeEngine:
        def create(self, sid, *a, **kw):
            return InterviewState(session_id=sid, resume_raw="test", profile={}), "opening"
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(api, "OpenAiLlm", lambda **kw: object())
    monkeypatch.setattr(api, "InterviewEngine", lambda llm: FakeEngine())
    with factory() as db:
        payload = CreateSessionRequest(resume_id=rid, interview_mode="full", interview_type="full", dedup_scope="none")
        tasks = BackgroundTasks()
        out = api.create_session(payload, tasks, db.get(User, uid), db)
        sid = out.session_id
        assert db.get(User, uid).platform_quota == 0
    task = tasks.tasks[0]
    task.func(*task.args, **task.kwargs)
    with factory() as db:
        assert db.get(InterviewSession, sid).status == "active"
        assert db.get(InterviewSession, sid).quota_state == "consumed"
        assert api._engine_for(db, db.get(User, uid), sid)
        assert db.get(User, uid).platform_quota == 0


def test_creation_failure_or_restart_timeout_refunds_without_resurrection(world):
    from app.services.billing import reserve_session_quota
    from app.services.creation_recovery import recover_expired_creations, fail_creation
    factory, _, (uid, rid, _), _ = world
    with factory() as db:
        session = InterviewSession(user_id=uid, resume_id=rid, interview_mode="full", interview_type="full",
                                   status="creating", creation_deadline=time.time() - 1)
        reserve_session_quota(db, db.get(User, uid), session)
        db.add(session)
        db.commit()
        sid = session.id
    with factory() as db:
        assert recover_expired_creations(db) == 1
        assert not fail_creation(db, sid)
        assert recover_expired_creations(db) == 0
        assert db.get(User, uid).platform_quota == 1
        assert db.get(InterviewSession, sid).status == "failed"


def test_submission_id_replays_and_rejects_content_reuse(world):
    from app.services.interview_operations import run_operation
    factory, _, (uid, _, sid), _ = world
    calls = []
    def action(session):
        calls.append(1)
        session.rounds_used += 1
        return {"message": "ok"}
    payload = {"text": "answer", "submission_id": "request-1", "expected_version": 1}
    with factory() as db:
        assert run_operation(db, sid, uid, "answer", payload, action) == {"message": "ok"}
        assert run_operation(db, sid, uid, "answer", payload, action) == {"message": "ok"}
        assert len(calls) == 1
        assert db.get(InterviewSession, sid).rounds_used == 1
        with pytest.raises(HTTPException) as err:
            run_operation(db, sid, uid, "answer", {**payload, "text": "different"}, action)
        assert err.value.status_code == 409


def test_shared_claim_blocks_other_channels_and_abandon(world):
    from app.services.interview_operations import run_operation
    # Pool size one: if a model callback can use another DB session, no claim transaction holds the pool.
    factory, _, (uid, _, sid), _ = world
    with factory() as db:
        def action(session):
            db.rollback()  # Simulate work with no pending writes; refresh version remains the claimed version.
            for kind in ["answer", "code", "abandon"]:
                with factory() as other:
                    with pytest.raises(HTTPException) as err:
                        run_operation(other, sid, uid, kind, {"submission_id": f"other-{kind}"}, lambda _: pytest.fail("must not execute"))
                    assert err.value.status_code == 409
            return {"ok": True}
        run_operation(db, sid, uid, "answer", {"submission_id": "first"}, action)


def test_failed_command_rolls_back_state_and_releases_claim(world):
    from app.services.interview_operations import run_operation
    factory, _, (uid, _, sid), _ = world
    with factory() as db:
        def fail(session):
            session.rounds_used = 99
            raise RuntimeError("model failed")
        with pytest.raises(RuntimeError):
            run_operation(db, sid, uid, "answer", {"submission_id": "failed"}, fail)
        session = db.get(InterviewSession, sid, populate_existing=True)
        assert session.rounds_used == 0
        assert session.pending_operation is None
        assert db.scalar(select(InterviewOperation.status)) == "failed"
        with pytest.raises(HTTPException) as err:
            run_operation(db, sid, uid, "answer", {"expected_version": 1}, lambda _: {})
        assert err.value.status_code == 409


def test_invalid_user_key_never_falls_back_to_platform():
    from app.services.llm.manager import resolve_llm_config
    with pytest.raises(HTTPException) as err:
        resolve_llm_config("deepseek", "deepseek-v4-flash", "corrupt-ciphertext", False)
    assert err.value.status_code == 409


def test_overload_alert_does_not_block_and_failed_delivery_backs_off(monkeypatch):
    from app.middleware import load_alert_middleware as middleware
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def slow_alert(*a, **kw):
        calls.append(1)
        started.set()
        release.wait(2)
        finished.set()
        return False
    monkeypatch.setattr(middleware, "send_throttled_ops_alert", slow_alert)
    monkeypatch.setattr(middleware, "_last_attempt", float("-inf"))
    monkeypatch.setattr(middleware, "_alert_inflight", False)
    monkeypatch.setattr(settings, "alert_rpm_threshold", 1)
    try:
        middleware._maybe_alert_overload(10)
        assert started.wait(1)
        assert not finished.is_set()
        middleware._maybe_alert_overload(10)
    finally:
        release.set()
    assert finished.wait(1)
    middleware._maybe_alert_overload(10)
    assert len(calls) == 1


def test_http_sse_ws_share_one_replayable_answer(world, monkeypatch):
    from app.api import interview as api, interview_ws
    from app.models import Question
    factory, _, (uid, _, sid), token = world
    client = client_for(world, monkeypatch)
    client.app.include_router(api.router)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr("app.services.session_checkpoint.save_checkpoint", lambda *a: 1)
    calls = []
    class FakeEngine:
        llm = object()
        def __init__(self, *args):
            pass
        def handle_intro(self, state, answer):
            calls.append(answer)
            state.stage = "ASKING"
            state.plan = [{"type": "qa", "text": "question", "topic": "topic"}]
            state.history.extend([{"role": "candidate", "text": answer}, {"role": "interviewer", "text": "question"}])
            return state, "question"
    monkeypatch.setattr(api, "_engine_for", lambda *a, **kw: FakeEngine())
    monkeypatch.setattr(api, "InterviewEngine", FakeEngine)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"text": "intro", "submission_id": "one-answer", "expected_version": 1}
    response = client.post(f"/api/interview/session/{sid}/answer", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    with factory() as db:
        # Even a final answer must be replayable after its session became finished.
        db.get(InterviewSession, sid).status = "finished"
        db.commit()
    response = client.post(f"/api/interview/session/{sid}/answer/stream", json=payload, headers=headers)
    assert response.status_code == 200
    assert "event: done" in response.text
    with client.websocket_connect(f"/ws/interview/{sid}?token={token}") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        ws.send_json({"type": "answer", **payload})
        assert ws.receive_json()["type"] == "done"
    assert calls == ["intro"]
    with factory() as db:
        assert len(list(db.scalars(select(Question)))) == 1
        assert len(list(db.scalars(select(InterviewOperation)))) == 1


def test_expired_claim_is_released_without_another_submission(world):
    from app.services.interview_operations import recover_expired_operations
    factory, _, (uid, _, sid), _ = world
    with factory() as db:
        session = db.get(InterviewSession, sid)
        session.pending_operation = "interrupted"
        session.operation_deadline = time.time() - 1
        db.add(InterviewOperation(session_id=sid, request_id="interrupted", fingerprint="x", status="processing"))
        db.commit()
        before = session.version
        assert recover_expired_operations(db) == 1
        db.refresh(session)
        assert session.pending_operation is None
        assert session.version > before
        assert db.scalar(select(InterviewOperation.status)) == "expired"
        assert recover_expired_operations(db) == 0


def test_expired_worker_cannot_commit_over_newer_session(world):
    from app.services.interview_operations import run_operation, recover_expired_operations
    # A distinct pool allows an independent recovery process, as in production.
    factory, engine, (uid, _, sid), _ = world
    other_engine = create_engine(engine.url)
    other_factory = sessionmaker(bind=other_engine)
    try:
        with factory() as db:
            def action(session):
                session.rounds_used = 99
                with other_factory() as other:
                    other.execute(update(InterviewSession).where(InterviewSession.id == sid)
                                  .values(operation_deadline=time.time() - 1))
                    other.commit()
                    assert recover_expired_operations(other) == 1
                return {"ok": True}
            with pytest.raises(HTTPException) as err:
                run_operation(db, sid, uid, "answer", {"submission_id": "slow"}, action)
            assert err.value.status_code == 409
            assert db.get(InterviewSession, sid, populate_existing=True).rounds_used == 0
    finally:
        other_engine.dispose()


def test_upgrade_adds_columns_without_losing_legacy_rows(monkeypatch):
    from app import db_migrate
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE interview_sessions (id INTEGER PRIMARY KEY, status VARCHAR(16))"))
        conn.execute(text("INSERT INTO interview_sessions (id, status) VALUES (7, 'creating')"))
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE resumes (id INTEGER PRIMARY KEY)"))
    monkeypatch.setattr(db_migrate, "engine", engine)
    try:
        db_migrate.ensure_schema()
        db_migrate.ensure_schema()
        columns = {c["name"] for c in inspect(engine).get_columns("interview_sessions")}
        assert {"version", "quota_state", "billing_source", "pending_operation", "creation_deadline", "last_submission_id"} <= columns
        with engine.connect() as conn:
            row = conn.execute(text("SELECT id, version, billing_source, creation_deadline FROM interview_sessions")).one()
            assert tuple(row[:3]) == (7, 1, "legacy")
            assert row[3] > time.time()
    finally:
        engine.dispose()


def test_readiness_detects_database_failure(world):
    from app.main import readiness
    factory, _, _, _ = world
    with factory() as db:
        assert readiness(db) == {"status": "ready"}
    class BrokenDb:
        def execute(self, *a):
            raise RuntimeError("private connection information")
    with pytest.raises(HTTPException) as err:
        readiness(BrokenDb())
    assert err.value.status_code == 503
    assert "private" not in err.value.detail


def test_register_login_and_admin_password_reset_roundtrip(world, monkeypatch):
    from app.api import admin
    factory, _, (uid, _, _), _ = world
    client = client_for(world, monkeypatch)
    client.app.include_router(admin.router)
    monkeypatch.setattr(admin, "_audit", lambda *a, **kw: None)
    res = client.post("/api/auth/register", json={"username": "new-user", "password": "first-password"})
    assert res.status_code == 201, res.text
    old_token = res.json()["access_token"]
    new_user_id = res.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {old_token}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/login", json={"username": "new-user", "password": "first-password"}).status_code == 200
    path = f"/api/admin/users/{new_user_id}/reset-password"
    assert client.post(path, json={"new_password": "second-password"}, headers=headers).status_code == 403
    with factory() as db:
        db.get(User, uid).is_admin = 1
        db.commit()
    assert client.post(path, json={"new_password": "second-password"},
                       headers={"Authorization": f"Bearer {world[3]}"}).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"username": "new-user", "password": "first-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "new-user", "password": "second-password"}).status_code == 200
