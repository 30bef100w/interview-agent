"""飞书群机器人 Webhook 通知（运维告警 / 错标审核批次报告）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("app.feishu_notify")

_STATE_PATH = Path(__file__).resolve().parents[2] / "logs" / "feishu_alert_state.json"


def _webhook_url() -> str:
    return (settings.feishu_webhook_url or "").strip()


def _webhook_secret() -> str:
    return (settings.feishu_webhook_secret or "").strip()


def _gen_sign(secret: str, timestamp: str) -> str:
    """飞书自定义机器人签名：HMAC-SHA256(timestamp + '\\n' + secret) 再 Base64。"""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def _load_state() -> dict[str, Any]:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(state: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def send_feishu_text(title: str, body: str) -> bool:
    """发送飞书文本消息；未配置 webhook 时静默跳过。"""
    url = _webhook_url()
    if not url:
        return False
    text = f"【{title}】\n{body}".strip()
    payload: dict[str, Any] = {"msg_type": "text", "content": {"text": text[:8000]}}
    secret = _webhook_secret()
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = _gen_sign(secret, timestamp)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if int(body.get("code", 0)) not in (0,):
                logger.warning("feishu webhook rejected: %s", body)
                return False
        return True
    except urllib.error.URLError as exc:
        logger.warning("feishu notify failed: %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("feishu notify failed: %s", exc)
        return False


def send_throttled_ops_alert(
    alert_key: str,
    title: str,
    *,
    cooldown_seconds: int | None = None,
    **fields: Any,
) -> bool:
    """同一 alert_key 在冷却期内只发一次飞书。"""
    from app.services.alert_throttle import mark_alert_sent, should_send_alert

    if not should_send_alert(alert_key, cooldown_seconds):
        return False
    ok = send_ops_alert(title, **fields)
    if ok:
        mark_alert_sent(alert_key)
    return ok


def send_ops_alert(title: str, **fields: Any) -> bool:
    lines = [
        f"时间：{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"环境：{settings.app_env}",
    ]
    for k, v in fields.items():
        if v is None or v == "":
            continue
        lines.append(f"{k}：{v}")
    return send_feishu_text(title, "\n".join(lines))


def maybe_notify_tag_mismatch_batch(db) -> bool:
    """pending 每累计满 N 条发一批飞书报告（默认 10）。"""
    from sqlalchemy import select

    from app.models.tag_mismatch import TagMismatchReview
    from app.services.tag_mismatch_queue import pending_count

    batch = max(1, int(settings.feishu_tag_mismatch_batch or 10))
    pending = pending_count(db)
    if pending < batch:
        return False

    state = _load_state()
    last = int(state.get("tag_mismatch_pending_at_last_alert") or 0)
    if pending - last < batch:
        return False

    rows = db.scalars(
        select(TagMismatchReview)
        .where(TagMismatchReview.status == "pending")
        .order_by(TagMismatchReview.id.desc())
        .limit(batch)
    ).all()
    if not rows:
        return False

    lines = [
        f"待审核累计 {pending} 条（本批展示最近 {len(rows)} 条）",
        "请在管理端或数据库处理 tag_mismatch_reviews。",
        "",
    ]
    for i, row in enumerate(reversed(rows), 1):
        q = (row.question or "")[:120]
        roles = row.tagged_roles or ""
        lane = row.lane or ""
        lines.append(f"{i}. [{lane}] {q}")
        if roles:
            lines.append(f"   标签岗位: {roles[:200]}")

    ok = send_feishu_text("题库错标审核队列", "\n".join(lines))
    if ok:
        state["tag_mismatch_pending_at_last_alert"] = pending
        _save_state(state)
    return ok
