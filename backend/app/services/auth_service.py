from datetime import datetime, timedelta, timezone
import hashlib
import hmac

import bcrypt
import jwt

from app.config import settings


def hash_password(password: str) -> str:
    validate_password_bytes(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def validate_password_bytes(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("密码的 UTF-8 编码不能超过 72 字节（中文通常占 3 字节）")
    return password


def verify_password(password: str, password_hash: str) -> bool:
    try:
        validate_password_bytes(password)
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _password_version(password_hash: str) -> str:
    # Never put the password hash itself in a client-readable JWT.
    return hmac.new(settings.jwt_secret.encode(), password_hash.encode(), hashlib.sha256).hexdigest()


def create_token(user_id: int, password_hash: str) -> str:
    payload = {
        "sub": str(user_id),
        "pv": _password_version(password_hash),
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> int | None:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "pv"]},
        )
        user_id = int(payload["sub"])
        return user_id if user_id > 0 else None
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        return None


def token_matches_password(token: str, password_hash: str) -> bool:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
                             options={"require": ["sub", "exp", "pv"]})
        version = payload["pv"]
        return isinstance(version, str) and hmac.compare_digest(version, _password_version(password_hash))
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        return False
