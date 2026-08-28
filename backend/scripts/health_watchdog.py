#!/usr/bin/env python3
"""健康检查 watchdog（在 backend 容器内运行，依赖已安装）。

服务器 cron（每 2 分钟）:
  */2 * * * * cd /home/ubuntu/face-agent && docker compose exec -T backend python scripts/health_watchdog.py >> logs/health_watchdog.log 2>&1

依赖 .env：FEISHU_WEBHOOK_URL；可选 HEALTH_CHECK_URL（默认探测 nginx 全链路）。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from app.services.alert_throttle import mark_alert_sent, should_send_alert
from app.services.feishu_notify import send_ops_alert, send_feishu_text

STATE_PATH = Path(__file__).resolve().parents[1] / "logs" / "health_watchdog_state.json"
HEALTH_URL = os.environ.get("HEALTH_CHECK_URL", "http://nginx/api/health").strip()
FAIL_THRESHOLD = max(1, int(os.environ.get("HEALTH_FAIL_THRESHOLD", "2")))
COOLDOWN = max(60, int(os.environ.get("ALERT_COOLDOWN_SECONDS", "600")))


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _check_health() -> tuple[bool, str]:
    req = urllib.request.Request(HEALTH_URL, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status != 200:
                return False, f"HTTP {resp.status}: {body[:200]}"
            data = json.loads(body) if body.strip().startswith("{") else {}
            if data.get("status") != "ok":
                return False, f"unexpected body: {body[:200]}"
            return True, "ok"
    except urllib.error.URLError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ok, detail = _check_health()
    state = _load_state()
    fails = int(state.get("consecutive_failures") or 0)
    was_down = bool(state.get("was_down"))

    if ok:
        if was_down and should_send_alert("health_recovered", COOLDOWN):
            send_feishu_text(
                "服务已恢复",
                f"健康检查恢复正常\nURL：{HEALTH_URL}",
            )
            mark_alert_sent("health_recovered")
        state["consecutive_failures"] = 0
        state["was_down"] = False
        _save_state(state)
        print("health ok")
        return 0

    fails += 1
    state["consecutive_failures"] = fails
    print(f"health fail #{fails}: {detail}")

    if fails >= FAIL_THRESHOLD and should_send_alert("health_down", COOLDOWN):
        send_ops_alert(
            "服务健康检查失败",
            url=HEALTH_URL,
            consecutive_failures=fails,
            error=detail[:400],
            hint="请 SSH 登录服务器执行 docker compose ps / logs",
        )
        mark_alert_sent("health_down")
        state["was_down"] = True

    _save_state(state)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
