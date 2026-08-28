"""LLM 设置与用量 API：用户配自己的 key/模型，查询在应用上花的钱。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models import LLMUsage, User, UserLlmSetting
from app.services.llm.manager import (
    encrypt_key,
    find_model,
    find_provider,
    list_providers,
    normalize_model_id,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LlmSettingIn(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    api_key: str = ""  # 空 = 使用系统默认 key


class LlmSettingOut(BaseModel):
    provider: str
    model: str
    use_default: bool  # True = 未配自己的 key，走系统默认
    catalog_version: int = 0
    catalog_updated: str = ""
    providers: list


def _catalog_meta() -> dict:
    raw = __import__("app.services.llm.manager", fromlist=["load_providers"]).load_providers()
    return {
        "catalog_version": int(raw.get("version") or 0),
        "catalog_updated": str(raw.get("updated") or ""),
    }


def _setting_out(
    *,
    provider: str,
    model: str,
    use_default: bool,
) -> LlmSettingOut:
    meta = _catalog_meta()
    return LlmSettingOut(
        provider=provider,
        model=model,
        use_default=use_default,
        providers=list_providers(),
        **meta,
    )


def _setting(db: Session, user_id: int) -> UserLlmSetting | None:
    return db.scalars(
        select(UserLlmSetting).where(UserLlmSetting.user_id == user_id)
    ).first()


@router.get("/llm")
def get_llm_setting(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LlmSettingOut:
    s = _setting(db, current_user.id)
    if s is None:
        return _setting_out(provider="deepseek", model="deepseek-v4-flash", use_default=True)
    model = normalize_model_id(s.provider, s.model)
    if model != s.model:
        s.model = model
        db.commit()
    return _setting_out(
        provider=s.provider,
        model=model,
        use_default=bool(s.is_default or not s.api_key_encrypted),
    )


@router.put("/llm")
def put_llm_setting(
    payload: LlmSettingIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LlmSettingOut:
    provider = find_provider(payload.provider)
    if provider is None:
        raise HTTPException(status_code=400, detail="不支持的模型服务商")
    if find_model(payload.provider, payload.model) is None:
        payload.model = normalize_model_id(payload.provider, payload.model)
    if find_model(payload.provider, payload.model) is None:
        raise HTTPException(status_code=400, detail="不支持的模型")
    api_key = (payload.api_key or "").strip()

    s = _setting(db, current_user.id)
    if s is None:
        s = UserLlmSetting(user_id=current_user.id)
        db.add(s)
    s.provider = payload.provider
    s.model = payload.model
    if api_key:
        s.api_key_encrypted = encrypt_key(api_key)
        s.is_default = 0
    else:
        # 清空 key → 回到系统默认
        s.api_key_encrypted = ""
        s.is_default = 1
    s.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _setting_out(
        provider=s.provider,
        model=s.model,
        use_default=bool(s.is_default or not s.api_key_encrypted),
    )


@router.get("/usage")
def get_usage(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(
        select(LLMUsage).where(LLMUsage.user_id == current_user.id)
    ).all()
    total_in = sum(r.input_tokens for r in rows)
    total_out = sum(r.output_tokens for r in rows)
    total_cost = sum(r.cost_yuan for r in rows)
    recent = [
        {
            "session_id": r.session_id,
            "provider": r.provider,
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost_yuan": r.cost_yuan,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows[-50:]
    ]
    recent.reverse()
    return {
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_cost_yuan": round(total_cost, 4),
        "session_count": len({r.session_id for r in rows if r.session_id}),
        "recent": recent,
    }


@router.get("/usage/session/{session_id}")
def get_session_usage(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(
        select(LLMUsage).where(
            LLMUsage.user_id == current_user.id,
            LLMUsage.session_id == session_id,
        )
    ).all()
    return {
        "session_id": session_id,
        "calls": len(rows),
        "input_tokens": sum(r.input_tokens for r in rows),
        "output_tokens": sum(r.output_tokens for r in rows),
        "cost_yuan": round(sum(r.cost_yuan for r in rows), 4),
    }
