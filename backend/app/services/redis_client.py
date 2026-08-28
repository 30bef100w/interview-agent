"""可选 Redis 客户端（checkpoint 等）；未配置 redis_url 时返回 None。"""
from __future__ import annotations

from app.config import settings

_client = None
_checked = False


def get_redis():
    global _client, _checked
    if _checked:
        return _client
    _checked = True
    url = (settings.redis_url or "").strip()
    if not url:
        return None
    try:
        import redis

        _client = redis.from_url(url, decode_responses=True, socket_connect_timeout=3)
        _client.ping()
    except Exception:  # noqa: BLE001
        _client = None
    return _client
