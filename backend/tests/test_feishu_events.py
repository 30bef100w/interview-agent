"""飞书事件 Webhook：验签、解密、展平。"""
import json

from app.services.feishu_dispatch import already_seen
from app.services.feishu_events import (
    encrypt_payload,
    extract_text,
    flatten_message_event,
    parse_callback,
    signature_hex,
)


SAMPLE = {
    "schema": "2.0",
    "header": {
        "event_id": "evt_1",
        "event_type": "im.message.receive_v1",
        "token": "verify-token",
    },
    "event": {
        "sender": {"sender_id": {"open_id": "ou_me"}, "sender_type": "user"},
        "message": {
            "message_id": "om_1",
            "chat_id": "oc_1",
            "chat_type": "p2p",
            "message_type": "text",
            "content": '{"text":"开始面试"}',
        },
    },
}


def test_url_verification(monkeypatch):
    from app.services import feishu_events as ev

    monkeypatch.setattr(ev.settings, "feishu_verification_token", "tok")
    monkeypatch.setattr(ev.settings, "feishu_encrypt_key", "")
    body = json.dumps(
        {"type": "url_verification", "token": "tok", "challenge": "abc"}
    ).encode()
    out = parse_callback(body)
    assert out["_url_verification"] is True
    assert out["challenge"] == "abc"


def test_url_verification_bad_token(monkeypatch):
    from app.services import feishu_events as ev

    monkeypatch.setattr(ev.settings, "feishu_verification_token", "tok")
    monkeypatch.setattr(ev.settings, "feishu_encrypt_key", "")
    body = json.dumps(
        {"type": "url_verification", "token": "nope", "challenge": "abc"}
    ).encode()
    try:
        parse_callback(body)
        raise AssertionError("expected FeishuEventError")
    except ev.FeishuEventError as exc:
        assert "token" in str(exc)


def test_flatten_v2_text():
    flat = flatten_message_event(SAMPLE)
    assert flat is not None
    assert flat["content"] == "开始面试"
    assert flat["sender_id"] == "ou_me"
    assert flat["chat_id"] == "oc_1"
    assert flat["chat_type"] == "p2p"


def test_extract_post():
    content = {
        "zh_cn": {
            "title": "标题",
            "content": [[{"tag": "text", "text": "你好"}]],
        }
    }
    assert extract_text("post", json.dumps(content)) == "标题你好"


def test_signature_and_encrypt(monkeypatch):
    from app.services import feishu_events as ev

    inner = json.dumps(
        {"type": "url_verification", "challenge": "c1", "token": "t"}
    )
    enc = encrypt_payload(inner, "ek")
    outer = json.dumps({"encrypt": enc}).encode()
    monkeypatch.setattr(ev.settings, "feishu_encrypt_key", "ek")
    monkeypatch.setattr(ev.settings, "feishu_verification_token", "t")
    sig = signature_hex("ts", "no", "ek", outer)
    out = parse_callback(outer, timestamp="ts", nonce="no", signature=sig)
    assert out["challenge"] == "c1"


def test_bad_signature(monkeypatch):
    from app.services import feishu_events as ev

    body = b'{"hello":1}'
    monkeypatch.setattr(ev.settings, "feishu_encrypt_key", "ek")
    monkeypatch.setattr(ev.settings, "feishu_verification_token", "")
    try:
        parse_callback(body, timestamp="1", nonce="n", signature="deadbeef")
        raise AssertionError("expected FeishuEventError")
    except ev.FeishuEventError as exc:
        assert "signature" in str(exc)


def test_skip_other_event_types():
    assert flatten_message_event({"header": {"event_type": "im.chat.member.bot.added_v1"}}) is None


def test_already_seen_dedupes():
    key = "om_test_dedupe_unique"
    assert already_seen(key) is False
    assert already_seen(key) is True


def test_webhook_endpoint_acks(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    got = []
    monkeypatch.setattr(
        "app.api.feishu.process_inbound_async", lambda event: got.append(event)
    )
    client = TestClient(app)
    res = client.post("/api/feishu/event", json=SAMPLE)
    assert res.status_code == 200
    assert res.json().get("code") == 0
    assert got and got[0]["content"] == "开始面试"


def test_webhook_challenge(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import feishu_events as ev

    monkeypatch.setattr(ev.settings, "feishu_verification_token", "")
    monkeypatch.setattr(ev.settings, "feishu_encrypt_key", "")
    client = TestClient(app)
    res = client.post(
        "/api/feishu/event",
        json={"type": "url_verification", "challenge": "hello", "token": ""},
    )
    assert res.status_code == 200
    assert res.json() == {"challenge": "hello"}
