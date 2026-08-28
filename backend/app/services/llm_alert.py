"""LLM 鉴权 / 余额类错误识别与飞书告警。"""
from __future__ import annotations

from app.services.feishu_notify import send_throttled_ops_alert

_BILLING_HINTS = (
    "insufficient",
    "balance",
    "quota",
    "billing",
    "payment",
    "credit",
    "余额",
    "额度",
    "欠费",
    "不足",
    "exceeded your current",
)


def is_llm_billing_or_auth_error(exc: BaseException) -> bool:
    """判断是否为 API Key 无效、余额不足、配额耗尽等运维需介入的错误。"""
    try:
        from openai import APIStatusError, AuthenticationError, PermissionDeniedError, RateLimitError
    except ImportError:
        APIStatusError = AuthenticationError = PermissionDeniedError = RateLimitError = ()  # type: ignore

    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return True
    if isinstance(exc, APIStatusError):
        code = int(getattr(exc, "status_code", 0) or 0)
        if code in (401, 402, 403):
            return True
        if code == 429 and _msg_has_billing_hint(str(exc)):
            return True
    if isinstance(exc, RateLimitError) and _msg_has_billing_hint(str(exc)):
        return True
    return _msg_has_billing_hint(str(exc))


def _msg_has_billing_hint(msg: str) -> bool:
    lower = (msg or "").lower()
    return any(h in lower for h in _BILLING_HINTS)


def maybe_alert_llm_failure(
    exc: BaseException,
    *,
    provider: str,
    model: str,
    used_platform_key: bool,
) -> None:
    if not used_platform_key or not is_llm_billing_or_auth_error(exc):
        return
    send_throttled_ops_alert(
        "llm_billing_platform",
        "平台 LLM Key 鉴权/余额异常",
        provider=provider,
        model=model,
        error=f"{type(exc).__name__}: {str(exc)[:400]}",
        hint="请检查 DeepSeek 控制台余额与 DEEPSEEK_API_KEY 是否有效",
    )
