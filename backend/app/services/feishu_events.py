"""飞书事件订阅 Webhook：验签、解密、展平为通道事件。"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from app.config import settings

logger = logging.getLogger("app.feishu_events")


class FeishuEventError(ValueError):
    pass


def signature_hex(timestamp: str, nonce: str, key: str, body: bytes) -> str:
    raw = f"{timestamp}{nonce}{key}".encode("utf-8") + body
    return hashlib.sha256(raw).hexdigest()


def decrypt_payload(encrypt: str, encrypt_key: str) -> bytes:
    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    blob = base64.b64decode(encrypt)
    if len(blob) < 17:
        raise FeishuEventError("encrypted payload too short")
    iv, data = blob[:16], blob[16:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(data) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def encrypt_payload(plain: str, encrypt_key: str) -> str:
    """测试用：生成与开放平台相同算法的密文。"""
    import os

    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    iv = os.urandom(16)
    padder = PKCS7(128).padder()
    padded = padder.update(plain.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    blob = iv + encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(blob).decode("ascii")


def parse_callback(
    body: bytes,
    *,
    timestamp: str = "",
    nonce: str = "",
    signature: str = "",
) -> dict[str, Any]:
    encrypt_key = (settings.feishu_encrypt_key or "").strip()
    verify_token = (settings.feishu_verification_token or "").strip()
    sign_key = encrypt_key or verify_token
    if signature and sign_key:
        expect = signature_hex(timestamp, nonce, sign_key, body)
        if expect != signature.strip().lower() and expect != signature.strip():
            # 飞书文档为 sha256 hex；有的网关带 sha256= 前缀
            got = signature.strip().lower().removeprefix("sha256=")
            if expect != got:
                raise FeishuEventError("invalid signature")
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise FeishuEventError("invalid json") from exc
    if not isinstance(payload, dict):
        raise FeishuEventError("invalid payload")
    enc = str(payload.get("encrypt") or "").strip()
    if enc:
        if not encrypt_key:
            raise FeishuEventError("encrypted event but FEISHU_ENCRYPT_KEY empty")
        try:
            payload = json.loads(decrypt_payload(enc, encrypt_key).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise FeishuEventError("decrypt failed") from exc
        if not isinstance(payload, dict):
            raise FeishuEventError("decrypted payload invalid")
    if str(payload.get("type") or "") == "url_verification":
        token = str(payload.get("token") or "").strip()
        if verify_token and token and token != verify_token:
            raise FeishuEventError("invalid verification token")
        challenge = str(payload.get("challenge") or "").strip()
        if not challenge:
            raise FeishuEventError("missing challenge")
        return {"_url_verification": True, "challenge": challenge}
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    token = str(header.get("token") or payload.get("token") or "").strip()
    if verify_token and token and token != verify_token:
        raise FeishuEventError("invalid verification token")
    return payload


def extract_text(message_type: str, content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, dict):
        data = content
    else:
        raw = str(content).strip()
        if not raw:
            return ""
        if not raw.startswith("{") and not raw.startswith("["):
            return raw
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw
    if not isinstance(data, dict):
        return str(content)
    if message_type == "text" or "text" in data:
        return str(data.get("text") or "").strip()
    post = data.get("zh_cn") or data.get("en_us") or data
    if isinstance(post, dict):
        title = str(post.get("title") or "").strip()
        bits = [title] if title else []
        for line in post.get("content") or []:
            if not isinstance(line, list):
                continue
            for item in line:
                if not isinstance(item, dict):
                    continue
                if item.get("tag") == "text":
                    bits.append(str(item.get("text") or ""))
        return "".join(bits).strip()
    return ""


def flatten_message_event(payload: dict) -> dict | None:
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    event_type = str(header.get("event_type") or payload.get("type") or event.get("type") or "")
    if event_type and event_type != "im.message.receive_v1":
        return None
    if not event and payload.get("message"):
        event = payload
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender_ids = sender.get("sender_id") if isinstance(sender.get("sender_id"), dict) else {}
    sender_id = str(
        sender_ids.get("open_id")
        or sender.get("open_id")
        or payload.get("sender_id")
        or ""
    ).strip()
    if not message and payload.get("content") is not None:
        return {
            "event_id": str(header.get("event_id") or payload.get("uuid") or ""),
            "message_id": str(payload.get("message_id") or ""),
            "chat_id": str(payload.get("chat_id") or ""),
            "chat_type": str(payload.get("chat_type") or ""),
            "sender_id": sender_id,
            "sender_type": str(sender.get("sender_type") or payload.get("sender_type") or "user"),
            "message_type": str(payload.get("message_type") or "text"),
            "content": extract_text(
                str(payload.get("message_type") or "text"), payload.get("content")
            ),
        }
    msg_type = str(message.get("message_type") or "text")
    chat_id = str(message.get("chat_id") or "").strip()
    if not chat_id:
        return None
    return {
        "event_id": str(header.get("event_id") or payload.get("uuid") or ""),
        "message_id": str(message.get("message_id") or ""),
        "chat_id": chat_id,
        "chat_type": str(message.get("chat_type") or ""),
        "sender_id": sender_id,
        "sender_type": str(sender.get("sender_type") or "user"),
        "message_type": msg_type,
        "content": extract_text(msg_type, message.get("content")),
    }
