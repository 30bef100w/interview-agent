from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
import urllib.parse

from app.api.deps import get_current_user, get_optional_user
from app.config import settings
from app.db import get_db
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services.auth_service import create_token, hash_password, verify_password
from app.services.billing import sync_admin_flag, touch_active
from app.services import feishu_oauth

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        created_at=user.created_at,
        is_admin=bool(user.is_admin),
        platform_quota=int(user.platform_quota or 0),
        feishu_bound=bool((user.feishu_open_id or "").strip()),
        feishu_name=(user.feishu_name or "").strip(),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    exists = db.scalar(select(User).where(User.username == payload.username))
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        platform_quota=int(settings.default_platform_quota),
    )
    sync_admin_flag(user)
    touch_active(user)
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_token(user.id), user=_user_out(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if int(getattr(user, "is_disabled", 0) or 0):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用，请联系管理员")
    changed = sync_admin_flag(user)
    touch_active(user)
    if changed:
        db.commit()
        db.refresh(user)
    else:
        db.commit()
    return TokenResponse(access_token=create_token(user.id), user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserOut:
    if sync_admin_flag(current_user):
        db.commit()
        db.refresh(current_user)
    return _user_out(current_user)


@router.get("/feishu/config")
def feishu_config() -> dict:
    return {"enabled": feishu_oauth.oauth_enabled()}


@router.get("/feishu/start")
def feishu_start(
    mode: str = Query(default="login"),
    current_user: User | None = Depends(get_optional_user),
) -> dict:
    mode = (mode or "login").strip().lower()
    if mode not in {"login", "bind"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="mode 只能是 login 或 bind")
    if mode == "bind" and current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录再绑定飞书")
    uid = current_user.id if current_user is not None and mode == "bind" else None
    return {"authorize_url": feishu_oauth.authorize_url(mode, uid)}


@router.get("/feishu/callback")
def feishu_callback(
    code: str = "",
    state: str = "",
    db: Session = Depends(get_db),
) -> RedirectResponse:
    origin = feishu_oauth.web_origin()

    def _fail(msg: str) -> RedirectResponse:
        q = urllib.parse.urlencode({"feishu_error": msg})
        return RedirectResponse(f"{origin}/login?{q}", status_code=302)

    if not code or not state:
        return _fail("飞书未返回授权码")
    try:
        payload = feishu_oauth.decode_oauth_state(state)
        token_data = feishu_oauth.exchange_code(code)
        info = feishu_oauth.fetch_userinfo(str(token_data.get("access_token") or ""))
        bind_user = None
        if payload.get("m") == "bind" and payload.get("uid"):
            bind_user = db.get(User, int(payload["uid"]))
            if bind_user is None:
                return _fail("绑定账号不存在")
        user = feishu_oauth.apply_feishu_identity(
            db,
            open_id=info["open_id"],
            union_id=info.get("union_id") or "",
            name=info.get("name") or "",
            bind_user=bind_user,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "飞书登录失败"
        return _fail(detail)
    except Exception:
        return _fail("飞书登录失败，请重试")
    jwt_token = create_token(user.id)
    if payload.get("m") == "bind":
        q = urllib.parse.urlencode({"feishu": "1"})
        return RedirectResponse(f"{origin}/settings?{q}", status_code=302)
    q = urllib.parse.urlencode({"token": jwt_token, "username": user.username})
    return RedirectResponse(f"{origin}/auth/feishu?{q}", status_code=302)


@router.post("/feishu/unbind")
def feishu_unbind(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    current_user.feishu_open_id = None
    current_user.feishu_union_id = None
    current_user.feishu_name = ""
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return _user_out(current_user)

