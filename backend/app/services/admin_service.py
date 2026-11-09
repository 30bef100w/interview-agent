"""运营业务层：用户管理、会话查询、统计与事务审计。"""
from datetime import datetime, timezone
import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import QuotaGrant, SystemLog, User, UserLlmSetting
from app.repositories.admin import AdminRepository
from app.schemas.admin import BUSINESS_TZ
from app.services.auth_service import hash_password
from app.services.billing import grant_platform_quota


def business_day_start(now: datetime | None = None) -> datetime:
    local = (now or datetime.now(timezone.utc)).astimezone(BUSINESS_TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)


def page_result(items: list, total: int, query) -> dict:
    return {"items": items, "total": total, "limit": query.limit, "offset": query.offset}


def json_value(value: str | None, fallback):
    try:
        return json.loads(value) if value else fallback
    except (ValueError, TypeError):
        return fallback


def commit_audit(db: Session, admin: User, message: str, *, path: str, detail: str = "") -> None:
    """业务写入和审计使用同一事务；任何一步失败都回滚。"""
    db.add(SystemLog(level="info", source="admin", path=path[:256], message=message[:512],
                     detail=detail[:2000], user_id=admin.id))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


class AdminService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AdminRepository(db)

    def user(self, user_id: int, *, lock: bool = False) -> User:
        user = self.repo.user(user_id, lock=lock)
        if user is None:
            raise HTTPException(404, "用户不存在")
        return user

    def user_items(self, users: list[User]) -> list[dict]:
        counts, costs, settings = self.repo.user_summaries([user.id for user in users])
        items = []
        for user in users:
            setting = settings.get(user.id)
            own_key = bool(setting and not setting.is_default and (setting.api_key_encrypted or "").strip())
            items.append({
                "id": user.id, "username": user.username, "is_admin": bool(user.is_admin),
                "is_test": bool(user.is_test),
                "is_disabled": bool(user.is_disabled), "platform_quota": int(user.platform_quota or 0),
                "uses_platform_key": not own_key, "has_own_key": own_key,
                "interview_count": int(counts.get(user.id, 0)),
                "platform_cost_yuan": round(float(costs.get(user.id, 0)), 4),
                "last_active_at": user.last_active_at, "created_at": user.created_at,
            })
        return items

    def users(self, query) -> dict:
        users, total = self.repo.users(query)
        return page_result(self.user_items(users), total, query)

    def user_detail(self, user_id: int) -> dict:
        item = self.user_items([self.user(user_id)])[0]
        item["recent_sessions"] = [{
            "id": row.id, "status": row.status, "mode": row.interview_mode,
            "type": row.interview_type, "started_at": row.started_at, "finished_at": row.finished_at,
        } for row in self.repo.recent_sessions(user_id)]
        item["quota_grants"] = [{
            "id": row.id, "admin_id": row.admin_id, "delta": row.delta,
            "note": row.note, "created_at": row.created_at,
        } for row in self.repo.quota_grants(user_id)]
        return item

    def update_user(self, user_id: int, body, admin: User) -> dict:
        user = self.user(user_id, lock=True)
        if user_id == admin.id and body.is_disabled:
            raise HTTPException(400, "不能禁用自己的账号")
        if user_id == admin.id and body.is_admin is False:
            raise HTTPException(400, "不能取消自己的管理员身份")
        changes = []
        for field in ("is_disabled", "is_admin", "is_test"):
            value = getattr(body, field)
            if value is not None:
                setattr(user, field, int(value))
                changes.append(f"{field}={int(value)}")
        if body.platform_quota is not None:
            old, new = int(user.platform_quota or 0), body.platform_quota
            # CAS 也适用于不支持 FOR UPDATE 的 SQLite，避免覆盖同时发生的扣次。
            if not self.repo.set_quota_if_current(user_id, old, new):
                self.db.rollback()
                raise HTTPException(409, "用户额度已变化，请刷新后重试")
            self.db.add(QuotaGrant(admin_id=admin.id, user_id=user_id, delta=new - old, note=f"管理员设置为 {new}"))
            changes.append(f"platform_quota={old}->{new}")
        if not changes:
            raise HTTPException(400, "没有要更新的字段")
        commit_audit(self.db, admin, f"更新用户 {user.username}: {', '.join(changes)}",
                     path=f"/api/admin/users/{user_id}", detail="; ".join(changes))
        self.db.refresh(user)
        return self.user_items([user])[0]

    def grant_quota(self, user_id: int, body, admin: User) -> dict:
        user = self.user(user_id)
        remaining = grant_platform_quota(self.db, admin=admin, user=user, delta=body.delta, note=body.note)
        commit_audit(self.db, admin, f"发放额度 {body.delta} → {user.username}，剩余 {remaining}",
                     path=f"/api/admin/users/{user_id}/quota", detail=body.note)
        return {"user_id": user.id, "username": user.username, "delta": body.delta, "platform_quota": remaining}

    def reset_password(self, user_id: int, body, admin: User) -> dict:
        user = self.user(user_id)
        user.password_hash = hash_password(body.new_password)
        commit_audit(self.db, admin, f"重置密码 → {user.username}", path=f"/api/admin/users/{user_id}/reset-password")
        return {"user_id": user.id, "username": user.username, "ok": True}

    def clear_llm_key(self, user_id: int, admin: User) -> dict:
        user = self.user(user_id, lock=True)
        setting = self.repo.user_setting(user_id)
        if setting is None:
            setting = UserLlmSetting(user_id=user_id)
            self.db.add(setting)
        setting.api_key_encrypted, setting.is_default = "", 1
        commit_audit(self.db, admin, f"清除 LLM Key → {user.username}", path=f"/api/admin/users/{user_id}/clear-llm-key")
        return {"user_id": user.id, "username": user.username, "has_own_key": False}

    def stats(self) -> dict:
        now = datetime.now(timezone.utc)
        day0 = business_day_start(now)
        month0 = business_day_start(now.astimezone(BUSINESS_TZ).replace(day=1))
        users, sessions, cost, grants, errors = self.repo.stats(day0, month0)
        return {
            "total_users": int(users[0]), "disabled_users": int(users[1]), "dau": int(users[2]), "mau": int(users[3]),
            "total_interviews": int(sessions[0]), "interviews_today": int(sessions[1]), "interviews_month": int(sessions[2]),
            "platform_cost_yuan": round(float(cost or 0), 4), "quota_granted_total": int(grants or 0),
            "error_log_count": int(errors or 0), "timezone": "Asia/Shanghai",
            "activity_basis": "persisted_answers_excluding_admin_and_test",
        }

    def logs(self, query) -> dict:
        rows, total = self.repo.logs(query)
        fields = ("id", "level", "source", "path", "message", "detail", "user_id", "created_at")
        return page_result([{field: getattr(row, field) for field in fields} for row in rows], total, query)

    def platform_usage(self, query) -> dict:
        rows, total, cost = self.repo.usage(query)
        fields = ("id", "user_id", "session_id", "provider", "model", "input_tokens", "output_tokens", "cost_yuan", "created_at")
        return {**page_result([{field: getattr(row, field) for field in fields} for row in rows], total, query),
                "total_cost_yuan": round(cost, 4)}

    def session_items(self, rows) -> list[dict]:
        questions, answers, usages = self.repo.session_summaries([row[0].id for row in rows])
        items = []
        for session, username in rows:
            usage = usages.get(session.id)
            items.append({
                "id": session.id, "user_id": session.user_id, "username": username,
                "status": session.status, "mode": session.interview_mode, "type": session.interview_type,
                "target_role": session.target_role, "target_company": session.target_company,
                "started_at": session.started_at, "finished_at": session.finished_at,
                "question_count": questions.get(session.id, 0), "answer_count": answers.get(session.id, 0),
                "rounds_used": session.rounds_used, "billing_source": session.billing_source,
                "quota_state": session.quota_state, "llm_calls": usage.calls if usage else 0,
                "cost_yuan": round(float(usage.cost or 0), 4) if usage else 0.0,
            })
        return items

    def sessions(self, query) -> dict:
        rows, total = self.repo.sessions(query)
        return page_result(self.session_items(rows), total, query)

    def session_detail(self, session_id: int) -> dict:
        row = self.repo.session(session_id)
        if row is None:
            raise HTTPException(404, "会话不存在")
        item = self.session_items([row])[0]
        item.update({"resume_id": row[0].resume_id, "stages": json_value(row[0].stages, []),
                     "report": json_value(self.repo.report(session_id), None)})
        return item

    def messages(self, session_id: int, query) -> dict:
        if self.repo.session(session_id) is None:
            raise HTTPException(404, "会话不存在")
        rows, total = self.repo.messages(session_id, query)
        items = [{"id": f"{row.role}:{row.id}", "question_id": row.question_id,
                  "q_index": row.q_index, "role": row.role, "content": row.content,
                  "created_at": row.created_at} for row in rows]
        return page_result(items, total, query)
