"""系统日志写入（运维页可读）。"""
import traceback

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import SystemLog


def write_log(
    *,
    level: str = "error",
    source: str = "",
    path: str = "",
    message: str = "",
    detail: str = "",
    user_id: int | None = None,
    db: Session | None = None,
) -> None:
    own = db is None
    session = db or SessionLocal()
    try:
        session.add(
            SystemLog(
                level=(level or "error")[:16],
                source=(source or "")[:64],
                path=(path or "")[:256],
                message=(message or "")[:512],
                detail=(detail or "")[:8000],
                user_id=user_id,
            )
        )
        if own:
            session.commit()
    except Exception:
        if own:
            session.rollback()
    finally:
        if own:
            session.close()


def write_exception(
    exc: BaseException,
    *,
    source: str = "",
    path: str = "",
    user_id: int | None = None,
) -> None:
    message = f"{type(exc).__name__}: {exc}"[:512]
    write_log(
        level="error",
        source=source,
        path=path,
        message=message,
        detail="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        user_id=user_id,
    )
    try:
        from app.services.feishu_notify import send_throttled_ops_alert

        send_throttled_ops_alert(
            "http_500",
            "服务器未捕获异常",
            source=source or "unhandled",
            path=path,
            error=message,
            user_id=user_id,
        )
    except Exception:
        pass
