"""管理员运维 API：统计、用户管理、错误日志。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db import get_db
from app.models import (
    InterviewSession,
    LLMUsage,
    QuotaGrant,
    SystemLog,
    TagMismatchReview,
    User,
    UserLlmSetting,
)
from app.services.auth_service import hash_password
from app.services.billing import grant_platform_quota, uses_platform_key
from app.services.system_log import write_log

router = APIRouter(prefix="/api/admin", tags=["admin"])


class QuotaGrantBody(BaseModel):
    delta: int = Field(..., description="正数发放，负数扣减")
    note: str = Field(default="", max_length=256)


class UserUpdateBody(BaseModel):
    is_disabled: bool | None = None
    is_admin: bool | None = None
    platform_quota: int | None = Field(default=None, ge=0)


class ResetPasswordBody(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


def _utc_day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _user_item(db: Session, u: User) -> dict:
    interview_count = (
        db.scalar(
            select(func.count())
            .select_from(InterviewSession)
            .where(InterviewSession.user_id == u.id)
        )
        or 0
    )
    setting = db.scalars(
        select(UserLlmSetting).where(UserLlmSetting.user_id == u.id)
    ).first()
    platform_cost = (
        db.scalar(
            select(func.coalesce(func.sum(LLMUsage.cost_yuan), 0.0)).where(
                LLMUsage.user_id == u.id,
                LLMUsage.used_platform_key == 1,
            )
        )
        or 0.0
    )
    return {
        "id": u.id,
        "username": u.username,
        "is_admin": bool(u.is_admin),
        "is_disabled": bool(getattr(u, "is_disabled", 0)),
        "platform_quota": int(u.platform_quota or 0),
        "uses_platform_key": uses_platform_key(db, u.id),
        "has_own_key": bool(
            setting
            and not setting.is_default
            and (setting.api_key_encrypted or "").strip()
        ),
        "interview_count": int(interview_count),
        "platform_cost_yuan": round(float(platform_cost), 4),
        "last_active_at": u.last_active_at,
        "created_at": u.created_at,
    }


def _audit(admin: User, message: str, *, path: str, detail: str = "") -> None:
    write_log(
        level="info",
        source="admin",
        path=path,
        message=message[:512],
        detail=detail[:2000],
        user_id=admin.id,
    )


@router.get("/stats")
def admin_stats(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    day0 = _utc_day_start(now)
    mau0 = day0 - timedelta(days=29)
    month0 = day0.replace(day=1)

    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    disabled_users = (
        db.scalar(
            select(func.count()).select_from(User).where(User.is_disabled == 1)
        )
        or 0
    )
    dau = (
        db.scalar(
            select(func.count()).select_from(User).where(User.last_active_at >= day0)
        )
        or 0
    )
    mau = (
        db.scalar(
            select(func.count()).select_from(User).where(User.last_active_at >= mau0)
        )
        or 0
    )

    total_interviews = (
        db.scalar(select(func.count()).select_from(InterviewSession)) or 0
    )
    interviews_today = (
        db.scalar(
            select(func.count())
            .select_from(InterviewSession)
            .where(InterviewSession.started_at >= day0)
        )
        or 0
    )
    interviews_month = (
        db.scalar(
            select(func.count())
            .select_from(InterviewSession)
            .where(InterviewSession.started_at >= month0)
        )
        or 0
    )

    platform_cost = (
        db.scalar(
            select(func.coalesce(func.sum(LLMUsage.cost_yuan), 0.0)).where(
                LLMUsage.used_platform_key == 1
            )
        )
        or 0.0
    )
    grants_total = (
        db.scalar(
            select(func.coalesce(func.sum(QuotaGrant.delta), 0)).where(
                QuotaGrant.delta > 0
            )
        )
        or 0
    )
    error_logs = (
        db.scalar(
            select(func.count())
            .select_from(SystemLog)
            .where(SystemLog.level == "error")
        )
        or 0
    )

    return {
        "total_users": int(total_users),
        "disabled_users": int(disabled_users),
        "dau": int(dau),
        "mau": int(mau),
        "total_interviews": int(total_interviews),
        "interviews_today": int(interviews_today),
        "interviews_month": int(interviews_month),
        "platform_cost_yuan": round(float(platform_cost), 4),
        "quota_granted_total": int(grants_total),
        "error_log_count": int(error_logs),
    }


@router.get("/users")
def admin_users(
    q: str = "",
    status_filter: str = Query(default="", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(User).order_by(User.id.desc())
    count_stmt = select(func.count()).select_from(User)
    keyword = (q or "").strip()
    if keyword:
        if keyword.isdigit():
            cond = or_(User.username.contains(keyword), User.id == int(keyword))
        else:
            cond = User.username.contains(keyword)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    sf = (status_filter or "").strip().lower()
    if sf == "disabled":
        stmt = stmt.where(User.is_disabled == 1)
        count_stmt = count_stmt.where(User.is_disabled == 1)
    elif sf == "active":
        stmt = stmt.where(User.is_disabled == 0)
        count_stmt = count_stmt.where(User.is_disabled == 0)
    elif sf == "admin":
        stmt = stmt.where(User.is_admin == 1)
        count_stmt = count_stmt.where(User.is_admin == 1)

    total = db.scalar(count_stmt) or 0
    users = db.scalars(stmt.offset(offset).limit(limit)).all()
    return {"items": [_user_item(db, u) for u in users], "total": int(total)}


@router.get("/users/{user_id}")
def admin_user_detail(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    item = _user_item(db, user)
    recent_sessions = db.scalars(
        select(InterviewSession)
        .where(InterviewSession.user_id == user_id)
        .order_by(InterviewSession.id.desc())
        .limit(10)
    ).all()
    grants = db.scalars(
        select(QuotaGrant)
        .where(QuotaGrant.user_id == user_id)
        .order_by(QuotaGrant.id.desc())
        .limit(20)
    ).all()
    item["recent_sessions"] = [
        {
            "id": s.id,
            "status": s.status,
            "mode": s.interview_mode,
            "type": s.interview_type,
            "started_at": s.started_at,
            "finished_at": s.finished_at,
        }
        for s in recent_sessions
    ]
    item["quota_grants"] = [
        {
            "id": g.id,
            "admin_id": g.admin_id,
            "delta": g.delta,
            "note": g.note,
            "created_at": g.created_at,
        }
        for g in grants
    ]
    return item


@router.patch("/users/{user_id}")
def admin_update_user(
    user_id: int,
    body: UserUpdateBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    changes: list[str] = []
    if body.is_disabled is not None:
        if user.id == admin.id and body.is_disabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="不能禁用自己的账号"
            )
        user.is_disabled = 1 if body.is_disabled else 0
        changes.append(f"is_disabled={user.is_disabled}")

    if body.is_admin is not None:
        if user.id == admin.id and not body.is_admin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="不能取消自己的管理员身份"
            )
        user.is_admin = 1 if body.is_admin else 0
        changes.append(f"is_admin={user.is_admin}")

    if body.platform_quota is not None:
        old = int(user.platform_quota or 0)
        new = int(body.platform_quota)
        user.platform_quota = new
        db.add(
            QuotaGrant(
                admin_id=admin.id,
                user_id=user.id,
                delta=new - old,
                note=f"管理员设置为 {new}",
            )
        )
        changes.append(f"platform_quota={old}->{new}")

    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有要更新的字段")

    db.commit()
    db.refresh(user)
    _audit(
        admin,
        f"更新用户 {user.username}: {', '.join(changes)}",
        path=f"/api/admin/users/{user_id}",
        detail="; ".join(changes),
    )
    return _user_item(db, user)


@router.post("/users/{user_id}/quota")
def admin_grant_quota(
    user_id: int,
    body: QuotaGrantBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    remaining = grant_platform_quota(
        db, admin=admin, user=user, delta=body.delta, note=body.note
    )
    db.commit()
    db.refresh(user)
    _audit(
        admin,
        f"发放额度 {body.delta} → {user.username}，剩余 {remaining}",
        path=f"/api/admin/users/{user_id}/quota",
        detail=body.note,
    )
    return {
        "user_id": user.id,
        "username": user.username,
        "delta": body.delta,
        "platform_quota": remaining,
    }


@router.post("/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: int,
    body: ResetPasswordBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    _audit(
        admin,
        f"重置密码 → {user.username}",
        path=f"/api/admin/users/{user_id}/reset-password",
    )
    return {"user_id": user.id, "username": user.username, "ok": True}


@router.post("/users/{user_id}/clear-llm-key")
def admin_clear_llm_key(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    setting = db.scalars(
        select(UserLlmSetting).where(UserLlmSetting.user_id == user_id)
    ).first()
    if setting is None:
        setting = UserLlmSetting(user_id=user_id)
        db.add(setting)
    setting.api_key_encrypted = ""
    setting.is_default = 1
    db.commit()
    _audit(
        admin,
        f"清除 LLM Key → {user.username}",
        path=f"/api/admin/users/{user_id}/clear-llm-key",
    )
    return {"user_id": user.id, "username": user.username, "has_own_key": False}


@router.get("/logs")
def admin_logs(
    level: str = "",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(SystemLog).order_by(SystemLog.id.desc())
    count_stmt = select(func.count()).select_from(SystemLog)
    if level.strip():
        lv = level.strip().lower()
        stmt = stmt.where(SystemLog.level == lv)
        count_stmt = count_stmt.where(SystemLog.level == lv)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.offset(offset).limit(limit)).all()
    return {
        "total": int(total),
        "items": [
            {
                "id": r.id,
                "level": r.level,
                "source": r.source,
                "path": r.path,
                "message": r.message,
                "detail": r.detail,
                "user_id": r.user_id,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


@router.get("/usage/platform")
def admin_platform_usage(
    limit: int = Query(default=50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    total_cost = (
        db.scalar(
            select(func.coalesce(func.sum(LLMUsage.cost_yuan), 0.0)).where(
                LLMUsage.used_platform_key == 1
            )
        )
        or 0.0
    )
    rows = db.scalars(
        select(LLMUsage)
        .where(LLMUsage.used_platform_key == 1)
        .order_by(LLMUsage.id.desc())
        .limit(limit)
    ).all()
    return {
        "total_cost_yuan": round(float(total_cost), 4),
        "items": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "session_id": r.session_id,
                "provider": r.provider,
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost_yuan": r.cost_yuan,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


class TagMismatchResolveBody(BaseModel):
    status: str = Field(..., description="resolved | dismissed")
    note: str = Field(default="", max_length=512)


class TagMismatchApplyBody(BaseModel):
    action: str = Field(..., description="update | delete")
    roles: list[str] = Field(default_factory=list)
    business_scene: list[str] = Field(default_factory=list)
    tech_scene: list[str] = Field(default_factory=list)
    company: str | None = None
    category: str | None = None
    note: str = Field(default="", max_length=512)


def _tag_mismatch_item(row: TagMismatchReview) -> dict:
    import json

    return {
        "id": row.id,
        "status": row.status,
        "lane": row.lane,
        "target_roles": json.loads(row.target_roles or "[]"),
        "question": row.question,
        "tagged_roles": json.loads(row.tagged_roles or "[]"),
        "tagged_scenes": json.loads(row.tagged_scenes or "[]"),
        "company": row.company,
        "category": row.category,
        "filter_reason": row.filter_reason,
        "session_id": row.session_id,
        "mq_message_id": row.mq_message_id,
        "note": row.note,
        "resolved_by": row.resolved_by,
        "created_at": row.created_at,
        "resolved_at": row.resolved_at,
    }


@router.get("/tag-mismatches/stats")
def admin_tag_mismatch_stats(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    pending = (
        db.scalar(
            select(func.count())
            .select_from(TagMismatchReview)
            .where(TagMismatchReview.status == "pending")
        )
        or 0
    )
    today0 = _utc_day_start()
    today_new = (
        db.scalar(
            select(func.count())
            .select_from(TagMismatchReview)
            .where(TagMismatchReview.created_at >= today0)
        )
        or 0
    )
    return {"pending": int(pending), "today_new": int(today_new)}


@router.get("/tag-mismatches")
def admin_tag_mismatches(
    status: str = Query(default="pending"),
    lane: str = "",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(TagMismatchReview).order_by(TagMismatchReview.id.desc())
    count_stmt = select(func.count()).select_from(TagMismatchReview)
    if status.strip():
        st = status.strip().lower()
        stmt = stmt.where(TagMismatchReview.status == st)
        count_stmt = count_stmt.where(TagMismatchReview.status == st)
    if lane.strip():
        ln = lane.strip()
        stmt = stmt.where(TagMismatchReview.lane == ln)
        count_stmt = count_stmt.where(TagMismatchReview.lane == ln)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.offset(offset).limit(limit)).all()
    return {
        "total": int(total),
        "items": [_tag_mismatch_item(r) for r in rows],
    }


@router.post("/tag-mismatches/{item_id}/resolve")
def admin_resolve_tag_mismatch(
    item_id: int,
    body: TagMismatchResolveBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(TagMismatchReview, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    st = body.status.strip().lower()
    if st not in {"resolved", "dismissed"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效状态")
    row.status = st
    row.note = (body.note or "")[:512]
    row.resolved_by = admin.id
    row.resolved_at = datetime.now(timezone.utc)
    db.commit()
    _audit(
        admin,
        f"错标审核 {st} → #{item_id}",
        path=f"/api/admin/tag-mismatches/{item_id}/resolve",
        detail=row.question[:200],
    )
    return _tag_mismatch_item(row)


@router.get("/question-bank/catalog")
def admin_question_bank_catalog(
    admin: User = Depends(require_admin),
) -> dict:
    from app.services.job_roles import all_roles, load_companies
    from app.services.question_bank_editor import load_scene_catalog

    roles = all_roles()
    companies = load_companies()["companies"]
    scenes = load_scene_catalog()
    return {
        "roles": [{"id": rid, "name": meta["name"]} for rid, meta in roles.items()],
        "companies": [{"id": c["id"], "name": c["name"]} for c in companies],
        "business_scenes": scenes["business_scenes"],
        "tech_scenes": scenes["tech_scenes"],
        "categories": [
            {"id": "bagu", "name": "八股"},
            {"id": "project", "name": "项目"},
        ],
    }


@router.get("/tag-mismatches/{item_id}/question")
def admin_tag_mismatch_question(
    item_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    import json

    from app.services.question_bank_editor import find_question

    row = db.get(TagMismatchReview, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    kb = find_question(row.question_norm)
    if kb:
        return {
            "found": True,
            "question": kb.get("question"),
            "roles": kb.get("roles") or [],
            "business_scene": kb.get("business_scene") or [],
            "tech_scene": kb.get("tech_scene") or [],
            "company": kb.get("company"),
            "category": kb.get("category") or "",
        }
    return {
        "found": False,
        "question": row.question,
        "roles": json.loads(row.tagged_roles or "[]"),
        "business_scene": [],
        "tech_scene": json.loads(row.tagged_scenes or "[]"),
        "company": row.company or None,
        "category": row.category or "",
    }


@router.post("/tag-mismatches/{item_id}/apply")
def admin_apply_tag_mismatch(
    item_id: int,
    body: TagMismatchApplyBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    from app.services.job_roles import all_roles, load_companies
    from app.services.question_bank_editor import (
        delete_question,
        load_scene_catalog,
        update_question,
    )

    row = db.get(TagMismatchReview, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    action = body.action.strip().lower()
    if action not in {"update", "delete"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效操作")

    role_ids = set(all_roles().keys())
    company_ids = {c["id"] for c in load_companies()["companies"]}
    scenes = load_scene_catalog()
    biz_ids = {s["id"] for s in scenes["business_scenes"]}
    tech_ids = {s["id"] for s in scenes["tech_scenes"]}

    try:
        if action == "delete":
            removed = delete_question(row.question_norm)
            kb_result = {"action": "delete", "removed": removed}
            audit_detail = f"删除题库 {removed} 条"
        else:
            roles = [r for r in body.roles if r in role_ids]
            if not roles:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="请至少选择一个有效岗位",
                )
            business_scene = [s for s in body.business_scene if s in biz_ids]
            tech_scene = [s for s in body.tech_scene if s in tech_ids]
            company = body.company if body.company in company_ids else None
            category = body.category if body.category in {"bagu", "project"} else "bagu"
            updated = update_question(
                row.question_norm,
                {
                    "roles": roles,
                    "business_scene": business_scene,
                    "tech_scene": tech_scene,
                    "company": company,
                    "category": category,
                },
            )
            kb_result = {"action": "update", "question": updated.get("question")}
            audit_detail = f"更新标签 roles={roles}"
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="题库文件 questions_dedup.jsonl 不存在，无法修改",
        ) from None
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="题库中未找到该题目，可能已被删除",
        ) from None

    row.status = "resolved"
    row.note = (body.note or audit_detail)[:512]
    row.resolved_by = admin.id
    row.resolved_at = datetime.now(timezone.utc)
    db.commit()
    _audit(
        admin,
        f"错标审核 apply:{action} → #{item_id}",
        path=f"/api/admin/tag-mismatches/{item_id}/apply",
        detail=row.question[:200],
    )
    return {"review": _tag_mismatch_item(row), "kb": kb_result}


@router.get("/question-bank/catalog")
def admin_question_bank_catalog(
    admin: User = Depends(require_admin),
) -> dict:
    from app.services.job_roles import all_roles, load_companies
    from app.services.question_bank_editor import load_scene_catalog

    roles = all_roles()
    companies = load_companies()["companies"]
    scenes = load_scene_catalog()
    return {
        "roles": [{"id": rid, "name": meta["name"]} for rid, meta in roles.items()],
        "companies": [{"id": c["id"], "name": c["name"]} for c in companies],
        "business_scenes": scenes["business_scenes"],
        "tech_scenes": scenes["tech_scenes"],
        "categories": [
            {"id": "bagu", "name": "八股"},
            {"id": "project", "name": "项目"},
        ],
    }


@router.get("/tag-mismatches/{item_id}/question")
def admin_tag_mismatch_question(
    item_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    import json

    from app.services.question_bank_editor import find_question

    row = db.get(TagMismatchReview, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    kb = find_question(row.question_norm)
    if kb:
        return {
            "found": True,
            "question": kb.get("question"),
            "roles": kb.get("roles") or [],
            "business_scene": kb.get("business_scene") or [],
            "tech_scene": kb.get("tech_scene") or [],
            "company": kb.get("company"),
            "category": kb.get("category") or "",
        }
    return {
        "found": False,
        "question": row.question,
        "roles": json.loads(row.tagged_roles or "[]"),
        "business_scene": [],
        "tech_scene": json.loads(row.tagged_scenes or "[]"),
        "company": row.company or None,
        "category": row.category or "",
    }


@router.post("/tag-mismatches/{item_id}/apply")
def admin_apply_tag_mismatch(
    item_id: int,
    body: TagMismatchApplyBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    from app.services.job_roles import all_roles, load_companies
    from app.services.question_bank_editor import (
        delete_question,
        load_scene_catalog,
        update_question,
    )

    row = db.get(TagMismatchReview, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    action = body.action.strip().lower()
    if action not in {"update", "delete"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效操作")

    role_ids = set(all_roles().keys())
    company_ids = {c["id"] for c in load_companies()["companies"]}
    scenes = load_scene_catalog()
    biz_ids = {s["id"] for s in scenes["business_scenes"]}
    tech_ids = {s["id"] for s in scenes["tech_scenes"]}

    try:
        if action == "delete":
            removed = delete_question(row.question_norm)
            kb_result = {"action": "delete", "removed": removed}
            audit_detail = f"删除题库 {removed} 条"
        else:
            roles = [r for r in body.roles if r in role_ids]
            if not roles:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="请至少选择一个有效岗位",
                )
            business_scene = [s for s in body.business_scene if s in biz_ids]
            tech_scene = [s for s in body.tech_scene if s in tech_ids]
            company = body.company if body.company in company_ids else None
            category = body.category if body.category in {"bagu", "project"} else "bagu"
            updated = update_question(
                row.question_norm,
                {
                    "roles": roles,
                    "business_scene": business_scene,
                    "tech_scene": tech_scene,
                    "company": company,
                    "category": category,
                },
            )
            kb_result = {"action": "update", "question": updated.get("question")}
            audit_detail = f"更新标签 roles={roles}"
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="题库文件 questions_dedup.jsonl 不存在，无法修改",
        ) from None
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="题库中未找到该题目，可能已被删除",
        ) from None

    row.status = "resolved"
    row.note = (body.note or audit_detail)[:512]
    row.resolved_by = admin.id
    row.resolved_at = datetime.now(timezone.utc)
    db.commit()
    _audit(
        admin,
        f"错标审核 apply:{action} → #{item_id}",
        path=f"/api/admin/tag-mismatches/{item_id}/apply",
        detail=row.question[:200],
    )
    return {"review": _tag_mismatch_item(row), "kb": kb_result}
