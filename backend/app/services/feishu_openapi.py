"""飞书开放平台 HTTP：tenant token + 发私聊。"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from app.config import settings
from app.services.feishu_cli import build_text_content, split_message

logger = logging.getLogger("app.feishu_openapi")

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"

_lock = threading.Lock()
_token = ""
_token_expire_at = 0.0


def openapi_enabled() -> bool:
    return bool((settings.feishu_app_id or "").strip() and (settings.feishu_app_secret or "").strip())


def tenant_access_token() -> str:
    global _token, _token_expire_at
    now = time.time()
    with _lock:
        if _token and now < _token_expire_at - 60:
            return _token
        body = json.dumps(
            {
                "app_id": settings.feishu_app_id.strip(),
                "app_secret": settings.feishu_app_secret.strip(),
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            _TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if int(data.get("code") or 0) != 0:
            raise RuntimeError(f"feishu tenant token failed: {data.get('msg')}")
        token = str(data.get("tenant_access_token") or "").strip()
        if not token:
            raise RuntimeError("feishu tenant token empty")
        _token = token
        _token_expire_at = now + int(data.get("expire") or 7200)
        return _token


def send_text(chat_id: str, text: str) -> None:
    if not chat_id:
        raise ValueError("chat_id required")
    token = tenant_access_token()
    url = f"{_SEND_URL}?{urllib.parse.urlencode({'receive_id_type': 'chat_id'})}"
    for chunk in split_message(text):
        payload = json.dumps(
            {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": build_text_content(chunk),
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        logger.info("feishu openapi send chat=%s chars=%s", chat_id, len(chunk))
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"feishu send http {exc.code}: {detail}") from exc
        if int(data.get("code") or 0) != 0:
            raise RuntimeError(f"feishu send failed: {data.get('msg')}")
