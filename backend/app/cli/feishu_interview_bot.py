"""深问飞书面试通道。

生产用网页 backend 收飞书私聊（进程内官方长连接，或 HTTP Webhook）。
本 CLI 仅本地调试：lark-cli 长连接。不要和线上 backend 同时开。
"""
from __future__ import annotations

import logging
import sys

from app.config import settings
from app.db import Base, engine
from app.db_migrate import ensure_schema
from app.services.feishu_cli import consume_messages
from app.services.feishu_dispatch import process_inbound

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app.feishu_bot")


def main() -> int:
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    logger.info(
        "feishu CLI consume (local/dev). binds=%s",
        settings.feishu_bind_users or "(none, use web OAuth)",
    )
    for event in consume_messages(identity="bot"):
        try:
            process_inbound(event)
        except Exception:
            logger.exception("feishu CLI handle failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
