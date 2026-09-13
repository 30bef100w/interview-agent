"""飞书网页 OAuth：授权 URL、换 token、绑定/登录深问账号。"""
from __future__ import annotations

import json
import logging
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.services.auth_service import hash_password
from app.services.billing import sync_admin_flag, touch_active

logger = logging.getLogger("app.feishu_oauth")

_AUTHORIZE = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
_TOKEN = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
_USERINFO = "https://open.feishu.cn/open-apis/authen/v1/user_info"


def oauth_enabled() -> bool:
    return bool((settings.feishu_app_id or "").strip() and (settings.feishu_app_secret or "").strip())


def web_origin() -> str:
    pub = (settings.public_origin or "").strip().rstrip("/")
    return pub or "http://localhost:3000"


def redirect_uri() -> str:
    explicit = (settings.feishu_redirect_uri or "").strip()
    if explicit:
        return explicit
    pub = (settings.public_origin or "").strip().rstrip("/")
    if pub:
        return f"{pub}/api/auth/feishu/callback"
    return "http://127.0.0.1:8001/api/auth/feishu/callback"


def encode_oauth_state(mode: str, user_id: int | None = None) -> str:
    payload = {
        "p": "feishu_oauth",
        "m": mode,
        "uid": user_id,
        "n": secrets.token_hex(8),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_oauth_state(state: str) -> dict:
    try:
        payload = jwt.decode(
            state, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="登录已过期，请重新点飞书登录") from exc
    if payload.get("p") != "feishu_oauth":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的飞书登录状态")
    return payload


def authorize_url(mode: str, user_id: int | None = None) -> str:
    if not oauth_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="尚未配置飞书应用")
    params = {
        "client_id": settings.feishu_app_id.strip(),
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "state": encode_oauth_state(mode, user_id),
    }
    scope = (settings.feishu_oauth_scope or "").strip()
    if scope:
        params["scope"] = scope
    return f"{_AUTHORIZE}?{urllib.parse.urlencode(params)}"


def next_username(base: str, taken: set[str]) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "", base or "")[:24] or "飞书用户"
    if cleaned not in taken:
        return cleaned
    for i in range(2, 50):
        cand = f"{cleaned}{i}"
        if cand not in taken:
            return cand
    return f"{cleaned}{secrets.token_hex(3)}"


def exchange_code(code: str) -> dict:
    body = json.dumps(
        {
            "grant_type": "authorization_code",
            "client_id": settings.feishu_app_id.strip(),
            "client_secret": settings.feishu_app_secret.strip(),
            "code": code,
            "redirect_uri": redirect_uri(),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        _TOKEN,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        logger.warning("feishu token http %s: %s", exc.code, detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="飞书授权失败，请重试") from exc
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="无法连接飞书授权服务") from exc
    if int(data.get("code") or 0) != 0 and not data.get("access_token"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(data.get("error_description") or data.get("msg") or "飞书换票失败"),
        )
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="飞书未返回用户凭证")
    return data


def fetch_userinfo(access_token: str) -> dict:
    req = urllib.request.Request(
        _USERINFO,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        logger.warning("feishu userinfo http %s: %s", exc.code, detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="读取飞书资料失败") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    open_id = str(data.get("open_id") or "").strip()
    if not open_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="飞书未返回用户标识")
    return {
        "open_id": open_id,
        "union_id": str(data.get("union_id") or "").strip(),
        "name": str(data.get("name") or data.get("en_name") or "").strip(),
    }


def apply_feishu_identity(
    db: Session,
    *,
    open_id: str,
    union_id: str,
    name: str,
    bind_user: User | None,
) -> User:
    existing = db.scalars(select(User).where(User.feishu_open_id == open_id)).first()
    if bind_user is not None:
        if existing is not None and existing.id != bind_user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="这个飞书号已经绑定了其他深问账号",
            )
        bind_user.feishu_open_id = open_id
        bind_user.feishu_union_id = union_id or None
        bind_user.feishu_name = (name or "")[:128]
        touch_active(bind_user)
        db.add(bind_user)
        db.commit()
        db.refresh(bind_user)
        return bind_user
    if existing is not None:
        if int(getattr(existing, "is_disabled", 0) or 0):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")
        if name and not (existing.feishu_name or "").strip():
            existing.feishu_name = name[:128]
        touch_active(existing)
        sync_admin_flag(existing)
        db.commit()
        db.refresh(existing)
        return existing
    taken = {u for u in db.scalars(select(User.username)).all() if u}
    user = User(
        username=next_username(name, taken),
        password_hash=hash_password(secrets.token_urlsafe(24)),
        platform_quota=int(settings.default_platform_quota),
        feishu_open_id=open_id,
        feishu_union_id=union_id or None,
        feishu_name=(name or "")[:128],
    )
    sync_admin_flag(user)
    touch_active(user)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
