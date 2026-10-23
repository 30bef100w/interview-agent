from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.services.auth_service import decode_token, token_matches_password

bearer = HTTPBearer(auto_error=False)


def authenticate_token(db: Session, token: str) -> User:
    """Shared HTTP/WS policy. No role changes are allowed during authentication."""
    user_id = decode_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = db.get(User, user_id, populate_existing=True)
    if user is None or not token_matches_password(token, user.password_hash):
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    if int(user.is_disabled or 0):
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    return authenticate_token(db, credentials.credentials)


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    try:
        return authenticate_token(db, credentials.credentials)
    except HTTPException:
        return None


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user
