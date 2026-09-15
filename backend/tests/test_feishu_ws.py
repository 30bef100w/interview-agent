"""飞书 WS 监听：只在生产 backend 启动。"""
from app.services.feishu_dispatch import process_inbound
from app.services.feishu_ws import payload_from_ws_event, start_feishu_ws, ws_should_start


def test_ws_disabled_outside_production(monkeypatch):
    from app.services import feishu_ws as ws

    monkeypatch.setattr(ws.settings, "app_env", "development")
    monkeypatch.setattr(ws.settings, "feishu_ws_enabled", True)
    monkeypatch.setattr(ws.settings, "feishu_app_id", "cli_x")
    monkeypatch.setattr(ws.settings, "feishu_app_secret", "secret")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert ws_should_start() is False


def test_ws_disabled_without_credentials(monkeypatch):
    from app.services import feishu_ws as ws

    monkeypatch.setattr(ws.settings, "app_env", "production")
    monkeypatch.setattr(ws.settings, "feishu_ws_enabled", True)
    monkeypatch.setattr(ws.settings, "feishu_app_id", "")
    monkeypatch.setattr(ws.settings, "feishu_app_secret", "")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert ws_should_start() is False


def test_ws_enabled_in_production(monkeypatch):
    from app.services import feishu_ws as ws

    monkeypatch.setattr(ws.settings, "app_env", "production")
    monkeypatch.setattr(ws.settings, "feishu_ws_enabled", True)
    monkeypatch.setattr(ws.settings, "feishu_app_id", "cli_x")
    monkeypatch.setattr(ws.settings, "feishu_app_secret", "secret")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert ws_should_start() is True


def test_start_is_noop_in_tests():
    assert start_feishu_ws() is False


def test_payload_from_ws_dict():
    payload = payload_from_ws_event(
        {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_me"}, "sender_type": "user"},
                "message": {
                    "message_id": "om_ws_1",
                    "chat_id": "oc_1",
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": '{"text":"你好"}',
                },
            },
        }
    )
    assert payload["event"]["message"]["chat_id"] == "oc_1"


def test_unbound_sender_replies(monkeypatch):
    from app.services import feishu_dispatch as disp

    got: list[tuple[str, str]] = []
    monkeypatch.setattr(disp, "send_markdown", lambda chat_id, text: got.append((chat_id, text)))

    class Runtime:
        def resolve_sender(self, open_id):
            return None

    monkeypatch.setattr(disp, "FeishuInterviewRuntime", lambda bind_map=None: Runtime())
    process_inbound(
        {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_unknown"}, "sender_type": "user"},
                "message": {
                    "message_id": "om_ws_unbound",
                    "chat_id": "oc_x",
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": '{"text":"开始"}',
                },
            },
        }
    )
    assert got and "绑定" in got[0][1]


def test_feishu_oauth_start_is_bind_only():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    login_mode = client.get("/api/auth/feishu/start?mode=login")
    assert login_mode.status_code == 400
    unbound = client.get("/api/auth/feishu/start")
    assert unbound.status_code == 401
