"""轻量补列：create_all 不会改已有表。兼容 SQLite 与 PostgreSQL。"""
from sqlalchemy import inspect, text

from app.db import engine


def _table_columns(conn, table: str) -> set[str]:
    dialect = conn.dialect.name
    if dialect == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return {str(row[1]) for row in rows}
    insp = inspect(conn)
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _add_column(conn, table: str, column: str, ddl: str) -> None:
    cols = _table_columns(conn, table)
    if column not in cols:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_schema() -> None:
    with engine.begin() as conn:
        _add_column(
            conn,
            "interview_sessions",
            "target_role",
            "target_role VARCHAR(128) DEFAULT ''",
        )
        _add_column(
            conn,
            "interview_sessions",
            "target_company",
            "target_company VARCHAR(128) DEFAULT ''",
        )
        _add_column(conn, "resumes", "analysis_json", "analysis_json TEXT")
        _add_column(
            conn,
            "resumes",
            "stored_path",
            "stored_path VARCHAR(512) DEFAULT ''",
        )
        _add_column(conn, "users", "is_admin", "is_admin INTEGER DEFAULT 0")
        _add_column(conn, "users", "platform_quota", "platform_quota INTEGER DEFAULT 3")
        _add_column(conn, "users", "last_active_at", "last_active_at TIMESTAMP")
        _add_column(conn, "users", "is_disabled", "is_disabled INTEGER DEFAULT 0")

        usage_cols = _table_columns(conn, "llm_usages")
        if usage_cols and "used_platform_key" not in usage_cols:
            conn.execute(
                text(
                    "ALTER TABLE llm_usages ADD COLUMN used_platform_key INTEGER DEFAULT 0"
                )
            )
