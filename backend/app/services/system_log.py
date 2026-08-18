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
    write_log(
        level="error",
        source=source,
        path=path,
        message=f"{type(exc).__name__}: {exc}"[:512],
        detail="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        user_id=user_id,
    )
