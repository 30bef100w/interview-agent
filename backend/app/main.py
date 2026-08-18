from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import models  # noqa: F401  确保模型注册进 Base.metadata
from app.api import (
    admin,
    auth,
    code,
    interview,
    meta,
    resume,
    settings as settings_api,
    voice,
)
from app.config import settings
from app.db import Base, engine
from app.db_migrate import ensure_schema
from app.services.system_log import write_exception


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(resume.router)
app.include_router(interview.router)
app.include_router(code.router)
app.include_router(voice.router)
app.include_router(settings_api.router)
app.include_router(meta.router)
app.include_router(admin.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    write_exception(exc, source="unhandled", path=str(request.url.path))
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
