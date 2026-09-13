"""深问飞书面试通道：lark-cli 收私聊，引擎出题后再发回去。

运行前：
1. 安装 lark-cli，应用具备 bot 发消息 / 接收消息事件
2. .env 配置 FEISHU_BIND_USERS=ou_xxx:深问用户名
3. 本机执行：python -m app.cli.feishu_interview_bot
"""
from __future__ import annotations

import logging
import sys
from collections import OrderedDict

from app.config import settings
from app.db import Base, engine
from app.db_migrate import ensure_schema
from app.services.feishu_channel import handle_inbound, parse_bind_map
from app.services.feishu_cli import consume_messages, send_markdown
from app.services.feishu_interview_runtime import FeishuInterviewRuntime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app.feishu_bot")

_SEEN_MAX = 256


def main() -> int:
    binds = parse_bind_map(settings.feishu_bind_users)
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    runtime = FeishuInterviewRuntime(bind_map=binds)
    seen: OrderedDict[str, None] = OrderedDict()
    logger.info("feishu interview bot listening, env_binds=%s", list(binds.values()) or "(none, use web OAuth)")
    for event in consume_messages(identity="bot"):
        chat_type = str(event.get("chat_type") or "")
        if chat_type and chat_type != "p2p":
            continue
        msg_id = str(event.get("message_id") or "")
        if msg_id:
            if msg_id in seen:
                continue
            seen[msg_id] = None
            if len(seen) > _SEEN_MAX:
                seen.popitem(last=False)
        chat_id = str(event.get("chat_id") or "")
        if not chat_id:
            continue

        def emit(text: str, *, _chat_id: str = chat_id) -> None:
            try:
                send_markdown(_chat_id, text)
            except Exception:
                logger.exception("feishu emit failed")

        try:
            replies = handle_inbound(event, runtime=runtime, emit=emit)
        except Exception:
            logger.exception("feishu handle failed")
            replies = ["这一轮处理出错了，请稍后再试，或改用网页。"]
        for text in replies:
            try:
                send_markdown(chat_id, text)
            except Exception:
                logger.exception("feishu reply failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
