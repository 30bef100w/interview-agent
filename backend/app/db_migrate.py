"""SQLite 轻量补列：create_all 不会改已有表。"""
from sqlalchemy import text

from app.db import engine


def ensure_schema() -> None:
    with engine.begin() as conn:
        cols = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(interview_sessions)")).fetchall()
        }
        if "target_role" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE interview_sessions ADD COLUMN target_role VARCHAR(128) DEFAULT ''"
                )
            )
        if "target_company" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE interview_sessions ADD COLUMN target_company VARCHAR(128) DEFAULT ''"
                )
            )

        resume_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(resumes)")).fetchall()
        }
        if "analysis_json" not in resume_cols:
            conn.execute(text("ALTER TABLE resumes ADD COLUMN analysis_json TEXT"))
        if "stored_path" not in resume_cols:
            conn.execute(
                text("ALTER TABLE resumes ADD COLUMN stored_path VARCHAR(512) DEFAULT ''")
            )

        user_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()
        }
        if "is_admin" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0"))
        if "platform_quota" not in user_cols:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN platform_quota INTEGER DEFAULT 3")
            )
        if "last_active_at" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_active_at DATETIME"))
        if "is_disabled" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_disabled INTEGER DEFAULT 0"))

        usage_cols = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(llm_usages)")).fetchall()
        }
        if usage_cols and "used_platform_key" not in usage_cols:
            conn.execute(
                text(
                    "ALTER TABLE llm_usages ADD COLUMN used_platform_key INTEGER DEFAULT 0"
                )
            )
