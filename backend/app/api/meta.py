"""岗位分类 / 企业表 / 简历推断岗位。"""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models import Resume, User
from app.services.job_roles import (
    all_categories,
    all_roles,
    infer_roles,
    load_companies,
    role_name,
)

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/job-catalog")
def job_catalog(
    current_user: User = Depends(get_current_user),
) -> dict:
    """岗位分级 + 企业表，供开练页选择。"""
    roles = all_roles()
    categories = []
    for cat, ids in all_categories().items():
        categories.append(
            {
                "name": cat,
                "roles": [
                    {"id": rid, "name": roles[rid]["name"]}
                    for rid in ids
                    if rid in roles
                ],
            }
        )
    companies = [
        {"id": c["id"], "name": c["name"]} for c in load_companies()["companies"]
    ]
    return {"categories": categories, "companies": companies}


@router.get("/infer-role")
def infer_role_from_resume(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """根据简历画像推断可能的目标岗位（可多选建议）。"""
    resume = db.get(Resume, resume_id)
    if resume is None or resume.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历不存在")
    profile = json.loads(resume.profile_json) if resume.profile_json else {}
    ids = infer_roles(profile)[:5]
    return {
        "resume_id": resume_id,
        "suggestions": [{"id": rid, "name": role_name(rid)} for rid in ids],
    }
