"""Explicit host-side role administration: python -m app.manage_admin --user-id 123."""
import argparse

from app.db import SessionLocal
from app.models import SystemLog, User


def main() -> None:
    parser = argparse.ArgumentParser(description="按已核验的用户 ID 显式设置管理员；不创建账号")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.get(User, args.user_id)
        if user is None:
            parser.error("用户不存在")
        user.is_admin = 0 if args.revoke else 1
        db.add(SystemLog(level="info", source="admin-bootstrap", path="cli:app.manage_admin",
                         message=f"host-side role change user_id={user.id} is_admin={user.is_admin}"))
        db.commit()
        print(f"user_id={user.id} is_admin={user.is_admin}")


if __name__ == "__main__":
    main()
