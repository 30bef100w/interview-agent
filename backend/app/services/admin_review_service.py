"""题库错标审核业务；数据库访问复用运营 Repository。"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import TagMismatchReview, User
from app.repositories.admin import AdminRepository
from app.services.admin_service import business_day_start, commit_audit, json_value, page_result
from app.services import question_bank_editor as editor
from app.services.job_roles import all_roles, load_companies


def review_item(row: TagMismatchReview) -> dict:
    item = {field: getattr(row, field) for field in (
        "id", "status", "lane", "question", "company", "category", "filter_reason",
        "session_id", "mq_message_id", "note", "resolved_by", "created_at", "resolved_at",
    )}
    for field in ("target_roles", "tagged_roles", "tagged_scenes"):
        value = json_value(getattr(row, field), [])
        item[field] = value if isinstance(value, list) else []
    return item


class AdminReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AdminRepository(db)

    def review(self, item_id: int) -> TagMismatchReview:
        row = self.db.get(TagMismatchReview, item_id)
        if row is None:
            raise HTTPException(404, "记录不存在")
        return row

    def stats(self) -> dict:
        pending, today = self.repo.review_stats(business_day_start())
        return {"pending": pending, "today_new": today}

    def list(self, query) -> dict:
        rows, total = self.repo.reviews(query)
        return page_result([review_item(row) for row in rows], total, query)

    def resolve(self, item_id: int, body, admin: User) -> dict:
        row = self.review(item_id)
        row.status, row.note = body.status, body.note
        row.resolved_by, row.resolved_at = admin.id, datetime.now(timezone.utc)
        commit_audit(self.db, admin, f"错标审核 {body.status} → #{item_id}",
                     path=f"/api/admin/tag-mismatches/{item_id}/resolve", detail=row.question[:200])
        return review_item(row)

    @staticmethod
    def catalog() -> dict:
        return {
            "roles": [{"id": rid, "name": meta["name"]} for rid, meta in all_roles().items()],
            "companies": [{"id": c["id"], "name": c["name"]} for c in load_companies()["companies"]],
            **editor.load_scene_catalog(),
            "categories": [{"id": "bagu", "name": "八股"}, {"id": "project", "name": "项目"}],
        }

    def question(self, item_id: int) -> dict:
        row = self.review(item_id)
        question = editor.find_question(row.question_norm)
        if question:
            return {"found": True, "question": question.get("question"),
                    "roles": question.get("roles") or [], "business_scene": question.get("business_scene") or [],
                    "tech_scene": question.get("tech_scene") or [], "company": question.get("company"),
                    "category": question.get("category") or ""}
        item = review_item(row)
        return {"found": False, "question": row.question, "roles": item["tagged_roles"],
                "business_scene": [], "tech_scene": item["tagged_scenes"],
                "company": row.company or None, "category": row.category or ""}

    def apply(self, item_id: int, body, admin: User) -> dict:
        row = self.review(item_id)
        try:
            if body.action == "delete":
                removed = editor.delete_question(row.question_norm)
                result, detail = {"action": "delete", "removed": removed}, f"删除题库 {removed} 条"
            else:
                catalog = self.catalog()
                roles = [role for role in dict.fromkeys(body.roles) if role in {r["id"] for r in catalog["roles"]}]
                if not roles:
                    raise HTTPException(400, "请至少选择一个有效岗位")
                patch = {"roles": roles, "category": body.category or "bagu"}
                for field, key in (("business_scene", "business_scenes"), ("tech_scene", "tech_scenes")):
                    valid = {item["id"] for item in catalog[key]}
                    patch[field] = [value for value in dict.fromkeys(getattr(body, field)) if value in valid]
                patch["company"] = body.company if body.company in {c["id"] for c in catalog["companies"]} else None
                updated = editor.update_question(row.question_norm, patch)
                result, detail = {"action": "update", "question": updated.get("question")}, f"更新标签 roles={roles}"
        except FileNotFoundError:
            raise HTTPException(404, "题库文件 questions_dedup.jsonl 不存在，无法修改") from None
        except LookupError:
            raise HTTPException(404, "题库中未找到该题目，可能已被删除") from None
        row.status, row.note = "resolved", (body.note or detail)[:512]
        row.resolved_by, row.resolved_at = admin.id, datetime.now(timezone.utc)
        commit_audit(self.db, admin, f"错标审核 apply:{body.action} → #{item_id}",
                     path=f"/api/admin/tag-mismatches/{item_id}/apply", detail=row.question[:200])
        return {"review": review_item(row), "kb": result}
