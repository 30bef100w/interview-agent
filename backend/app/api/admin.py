"""运营 Controller：统一鉴权、请求校验，委托 Service 执行业务。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db import get_db
from app.models import User
from app.schemas.admin import (
    AdminLogItem, AdminMessageItem, AdminSessionItem, AdminUserItem, AnalyticsQuery,
    LogQuery, MessageQuery, QuotaGrantBody, ResetPasswordBody, ReviewQuery,
    MAX_DATABASE_ID, PageResponse, PlatformUsageResponse,
    SessionQuery, TagMismatchApplyBody, TagMismatchResolveBody, UsageQuery,
    UserQuery, UserUpdateBody,
)
from app.services.admin_review_service import AdminReviewService
from app.services.admin_service import AdminService
from app.services.admin_trace_service import AdminTraceService
from app.services.admin_analytics_service import AdminAnalyticsService

# 每个运营接口自动经过管理员校验；新加路由也受同一边界保护。
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])
Admin = Annotated[User, Depends(require_admin)]
ResourceId = Annotated[int, Path(gt=0, le=MAX_DATABASE_ID)]


def get_admin_service(db: Session = Depends(get_db)) -> AdminService:
    return AdminService(db)


def get_review_service(db: Session = Depends(get_db)) -> AdminReviewService:
    return AdminReviewService(db)


Service = Annotated[AdminService, Depends(get_admin_service)]
Reviews = Annotated[AdminReviewService, Depends(get_review_service)]


@router.get("/stats")
def admin_stats(service: Service) -> dict:
    return service.stats()


@router.get("/analytics")
def admin_analytics(query: Annotated[AnalyticsQuery, Query()], db: Session = Depends(get_db)) -> dict:
    return AdminAnalyticsService(db).overview(query)


@router.get("/users", response_model=PageResponse[AdminUserItem])
def admin_users(query: Annotated[UserQuery, Query()], service: Service) -> dict:
    return service.users(query)


@router.get("/users/{user_id}")
def admin_user_detail(user_id: ResourceId, service: Service) -> dict:
    return service.user_detail(user_id)


@router.patch("/users/{user_id}", response_model=AdminUserItem)
def admin_update_user(user_id: ResourceId, body: UserUpdateBody, admin: Admin, service: Service) -> dict:
    return service.update_user(user_id, body, admin)


@router.post("/users/{user_id}/quota")
def admin_grant_quota(user_id: ResourceId, body: QuotaGrantBody, admin: Admin, service: Service) -> dict:
    return service.grant_quota(user_id, body, admin)


@router.post("/users/{user_id}/reset-password")
def admin_reset_password(user_id: ResourceId, body: ResetPasswordBody, admin: Admin, service: Service) -> dict:
    return service.reset_password(user_id, body, admin)


@router.post("/users/{user_id}/clear-llm-key")
def admin_clear_llm_key(user_id: ResourceId, admin: Admin, service: Service) -> dict:
    return service.clear_llm_key(user_id, admin)


@router.get("/logs", response_model=PageResponse[AdminLogItem])
def admin_logs(query: Annotated[LogQuery, Query()], service: Service) -> dict:
    return service.logs(query)


@router.get("/usage/platform", response_model=PlatformUsageResponse)
def admin_platform_usage(query: Annotated[UsageQuery, Query()], service: Service) -> dict:
    return service.platform_usage(query)


@router.get("/sessions", response_model=PageResponse[AdminSessionItem])
def admin_sessions(query: Annotated[SessionQuery, Query()], service: Service) -> dict:
    return service.sessions(query)


@router.get("/sessions/{session_id}")
def admin_session_detail(session_id: ResourceId, service: Service) -> dict:
    return service.session_detail(session_id)


@router.get("/sessions/{session_id}/messages", response_model=PageResponse[AdminMessageItem])
def admin_session_messages(session_id: ResourceId, query: Annotated[MessageQuery, Query()], service: Service) -> dict:
    return service.messages(session_id, query)


@router.get("/sessions/{session_id}/trace")
def admin_session_trace(session_id: ResourceId, db: Session = Depends(get_db)) -> dict:
    return AdminTraceService(db).trace(session_id)


@router.get("/tag-mismatches/stats")
def admin_tag_mismatch_stats(service: Reviews) -> dict:
    return service.stats()


@router.get("/tag-mismatches")
def admin_tag_mismatches(query: Annotated[ReviewQuery, Query()], service: Reviews) -> dict:
    return service.list(query)


@router.post("/tag-mismatches/{item_id}/resolve")
def admin_resolve_tag_mismatch(item_id: ResourceId, body: TagMismatchResolveBody, admin: Admin, service: Reviews) -> dict:
    return service.resolve(item_id, body, admin)


@router.get("/question-bank/catalog")
def admin_question_bank_catalog() -> dict:
    return AdminReviewService.catalog()


@router.get("/tag-mismatches/{item_id}/question")
def admin_tag_mismatch_question(item_id: ResourceId, service: Reviews) -> dict:
    return service.question(item_id)


@router.post("/tag-mismatches/{item_id}/apply")
def admin_apply_tag_mismatch(item_id: ResourceId, body: TagMismatchApplyBody, admin: Admin, service: Reviews) -> dict:
    return service.apply(item_id, body, admin)
