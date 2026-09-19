"""发给面试客户端的错误文案：内部异常不得原文下发。"""
from __future__ import annotations

import re

_ALLOWED = {
    "会话不存在",
    "面试已结束",
    "未登录或 token 无效",
    "回答不能为空",
    "无效 JSON",
}

_INTERNAL = re.compile(
    r"traceback|nameerror|typeerror|keyerror|attributeerror|not defined|"
    r"sqlalchemy|psycopg|redis|get_redis|nonetype|uvicorn|fastapi|"
    r"file \".+\", line |internal server",
    re.I,
)

_FALLBACK = "面试官暂时没跟上，请再试一次"


def public_error_message(err: object) -> str:
    """把异常收成候选人能看的一句话；Python/栈信息不透出。"""
    detail = getattr(err, "detail", None)
    if isinstance(detail, str) and detail.strip():
        text = detail.strip()
    elif isinstance(err, str):
        text = err.strip()
    else:
        text = str(err or "").strip()
    if not text:
        return _FALLBACK
    if text in _ALLOWED or text.startswith("未知消息类型"):
        return text
    if _INTERNAL.search(text) or len(text) > 80:
        return _FALLBACK
    if any(ch in text for ch in ("\\", "/", "'", '"')):
        return _FALLBACK
    return text
