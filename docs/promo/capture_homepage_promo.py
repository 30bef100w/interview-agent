"""截取主页展示图（测试账号，不含真实个人信息）。

输出：
  frontend/public/hero-session.png
  frontend/public/promo/01-dashboard.png
  frontend/public/promo/09-interview-chat.png
  frontend/public/promo/11-report.png
  docs/promo/images/（同步副本）

用法：
  python docs/promo/capture_homepage_promo.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import requests
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "frontend" / "public"
IMG_DIR = Path(__file__).resolve().parent / "images"

# 本地 Next dev 对 127.0.0.1 + Playwright 内置 Chromium 可能 403 静态 chunk，优先 localhost + Chrome
BASE_URL = os.environ.get("PROMO_BASE_URL", "http://localhost:3000")
API_URL = os.environ.get("PROMO_API_URL", "http://127.0.0.1:8001")

# 测试账号：简历为虚构「张三」，无真实姓名/电话
DASHBOARD_USER = os.environ.get("PROMO_DASHBOARD_USER", "smoke_fin_5499")
CHAT_USER = os.environ.get("PROMO_CHAT_USER", "smoke_m7_7955")
PASSWORD = os.environ.get("PROMO_PASSWORD", "test123456")
CHAT_SESSION_ID = int(os.environ.get("PROMO_CHAT_SESSION_ID", "8"))
REPORT_SESSION_ID = int(os.environ.get("PROMO_REPORT_SESSION_ID", "9"))

VIEWPORT = {"width": 1440, "height": 900}
DEVICE_SCALE = 2
FORBIDDEN_TEXT = ("许永琪", "xuyongqi", "xyq20020308")


def login_token(username: str) -> tuple[str, str]:
    resp = requests.post(
        f"{API_URL}/api/auth/login",
        json={"username": username, "password": PASSWORD},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    user = data.get("user") or {}
    return data["access_token"], str(user.get("username", username))


def inject_auth(page: Page, token: str, username: str) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
    page.evaluate(
        """([token, username]) => {
          localStorage.setItem('token', token);
          localStorage.setItem('username', username);
          localStorage.setItem('is_admin', '0');
          localStorage.setItem('fa_onboarding_done', '1');
        }""",
        [token, username],
    )


def dismiss_overlays(page: Page) -> None:
    page.evaluate("localStorage.setItem('fa_onboarding_done', '1')")
    for sel in [
        "button:has-text('知道了')",
        "button:has-text('跳过')",
        "button:has-text('关闭')",
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=500):
                btn.click()
                page.wait_for_timeout(200)
        except Exception:
            pass


def assert_no_private_info(page: Page, label: str) -> None:
    body = page.inner_text("body")
    for text in FORBIDDEN_TEXT:
        if text in body:
            raise RuntimeError(f"{label} 截图仍含隐私文本: {text}")


def shot(
    page: Page,
    path: Path,
    url: str,
    *,
    wait_selector: str | None = None,
    wait_ms: int = 2000,
    label: str = "",
) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    dismiss_overlays(page)
    if wait_selector:
        page.wait_for_selector(wait_selector, timeout=120_000)
    page.wait_for_timeout(wait_ms)
    assert_no_private_info(page, label or path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), type="png", full_page=False)
    print(f"OK {path.relative_to(ROOT)}")


def main() -> int:
    targets = [
        (
            PUBLIC / "hero-session.png",
            "chat",
            f"/interview/{CHAT_SESSION_ID}",
            "text=Redis",
            "hero-session",
        ),
        (
            PUBLIC / "promo" / "09-interview-chat.png",
            "chat",
            f"/interview/{CHAT_SESSION_ID}",
            "text=Redis",
            "09-interview-chat",
        ),
        (
            PUBLIC / "promo" / "01-dashboard.png",
            "dash",
            "/dashboard",
            f"text={DASHBOARD_USER}",
            "01-dashboard",
        ),
        (
            PUBLIC / "promo" / "11-report.png",
            "dash",
            f"/report/{REPORT_SESSION_ID}",
            "text=能力雷达图",
            "11-report",
        ),
    ]

    tokens: dict[str, tuple[str, str]] = {}
    for key, user in (("dash", DASHBOARD_USER), ("chat", CHAT_USER)):
        tokens[key] = login_token(user)
        print(f"login {user} OK")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            channel=os.environ.get("PROMO_BROWSER_CHANNEL", "chrome"),
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=DEVICE_SCALE,
            locale="zh-CN",
        )

        for out_path, auth_key, route, wait_selector, label in targets:
            token, username = tokens[auth_key]
            page = context.new_page()
            inject_auth(page, token, username)
            shot(
                page,
                out_path,
                f"{BASE_URL}{route}",
                wait_selector=wait_selector,
                wait_ms=2500,
                label=label,
            )
            page.close()

        browser.close()

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("01-dashboard.png", "09-interview-chat.png", "11-report.png"):
        src = PUBLIC / "promo" / name
        if src.is_file():
            shutil.copy2(src, IMG_DIR / name)

    print("\nDone. Homepage promo images use test accounts:")
    print(f"  dashboard/report: {DASHBOARD_USER} (session {REPORT_SESSION_ID})")
    print(f"  interview/hero:   {CHAT_USER} (session {CHAT_SESSION_ID})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        raise
