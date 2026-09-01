import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import models  # noqa: F401  确保模型注册进 Base.metadata
from app.middleware.load_alert_middleware import LoadAlertMiddleware
from app.middleware.trace_middleware import TraceMiddleware
from app.api import (
    admin,
    auth,
    code,
    feedback,
    interview,
    interview_ws,
    meta,
    observability,
    resume,
    settings as settings_api,
    voice,
)
from app.config import settings
from app.db import Base, engine
from app.db_migrate import ensure_schema
from app.services.system_log import write_exception


def _configure_logging() -> None:
    """app.* INFO 埋点：控制台 + logs/interview.log（uvicorn 已占 handler 时也生效）。"""
    from pathlib import Path

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    log_dir = Path(__file__).resolve().parents[1] / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "interview.log"

    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    if not any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == str(log_file)
        for h in app_logger.handlers
    ):
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        app_logger.addHandler(fh)
        app_logger.propagate = True

    root = logging.getLogger()
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


_configure_logging()


def _validate_settings() -> None:
    if not settings.is_production:
        return
    if settings.jwt_secret in ("", "dev-secret-change-me"):
        raise RuntimeError("生产环境必须设置 JWT_SECRET（不能使用默认值）")
    if settings.debug:
        logging.getLogger("app").warning("APP_ENV=production 但 DEBUG=true，建议关闭")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_settings()
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

app.add_middleware(LoadAlertMiddleware)
app.add_middleware(TraceMiddleware)

_cors = settings.cors_origin_list
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(feedback.router)
app.include_router(resume.router)
app.include_router(interview.router)
app.include_router(interview_ws.router)
app.include_router(code.router)
app.include_router(voice.router)
app.include_router(settings_api.router)
app.include_router(meta.router)
app.include_router(admin.router)
app.include_router(observability.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    write_exception(exc, source="unhandled", path=str(request.url.path))
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
