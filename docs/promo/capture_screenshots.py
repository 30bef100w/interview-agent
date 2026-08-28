"""同步用户参考截图并高清放大，或尝试 Playwright 实时截取。"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import requests
from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
IMG_DIR = Path(__file__).resolve().parent / "images"
ASSETS_DIR = Path(
    os.environ.get(
        "PROMO_ASSETS_DIR",
        r"C:\Users\21236\.cursor\projects\d-student-project-work-project-face-agent\assets",
    )
)
DB_PATH = BACKEND / "data" / "face_agent.db"

BASE_URL = os.environ.get("PROMO_BASE_URL", "http://127.0.0.1:3000")
API_URL = os.environ.get("PROMO_API_URL", "http://127.0.0.1:8001")
USERNAME = os.environ.get("PROMO_USERNAME", "smoke_fin_5499")
PASSWORD = os.environ.get("PROMO_PASSWORD", "test123456")
USER_ID = int(os.environ.get("PROMO_USER_ID", "9"))
VIEWPORT = {"width": 1440, "height": 900}
DEVICE_SCALE = 2
TARGET_WIDTH = 2880

# 默认从测试账号参考截图同步（可用 PROMO_MODE=live 实时截取）
REFERENCE_MAP: dict[str, str] = {
    "00-landing.png": "*image-fe8042be*",
    "01-dashboard.png": "*image-1dc3cfef*",
    "02-new-interview.png": "*image-252e1f94*",
    "03-custom-settings.png": "*image-71cc607e*",
    "04-target-company.png": "*image-42c6f67c*",
    "05-history.png": "*image-5c97d967*",
    "06-growth.png": "*image-e2194111*",
    "07-targeted-practice.png": "*image-cedf9cc9*",
    "08-radar-weakness.png": "*image-475ff808*",
    "09-interview-chat.png": "*image-c5f62127*",
    "10-coding.png": "*image-11bca58d*",
    "11-report.png": "*image-5d35ea8e*",
    "12-report-questions.png": "*image-31bbf1a8*",
}


def upscale_image(src: Path, dst: Path, target_width: int = TARGET_WIDTH) -> None:
    with Image.open(src) as im:
        w, h = im.size
        if w < target_width:
            ratio = target_width / w
            im = im.resize((target_width, int(h * ratio)), Image.Resampling.LANCZOS)
        im.save(dst, format="PNG", optimize=True)


def find_asset(pattern: str) -> Path | None:
    matches = sorted(ASSETS_DIR.glob(pattern))
    return matches[0] if matches else None


def sync_reference_images() -> list[str]:
    """从用户参考截图同步并放大，内容与手工截图一致。"""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    done: list[str] = []
    missing: list[str] = []
    for out_name, pattern in REFERENCE_MAP.items():
        src = find_asset(pattern)
        dst = IMG_DIR / out_name
        if not src:
            missing.append(out_name)
            continue
        upscale_image(src, dst)
        done.append(out_name)
        print(f"OK {out_name} <- {src.name}")
    if missing:
        print("Missing references:", ", ".join(missing), file=sys.stderr)
    return done


def pick_sessions() -> dict[str, int]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """
        SELECT id, status, state_json
        FROM interview_sessions
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (USER_ID,),
    ).fetchall()
    conn.close()

    chat_id = None
    report_id = None
    best_hist = -1
    for sid, status, state_json in rows:
        hist_len = 0
        stage = ""
        if state_json:
            st = json.loads(state_json)
            hist = st.get("history") or []
            hist_len = len(hist) if isinstance(hist, list) else 0
            stage = st.get("stage", "")
        if status == "finished" and report_id is None:
            report_id = sid
        if status == "active" and stage == "ASKING" and hist_len > best_hist:
            chat_id = sid
            best_hist = hist_len
    return {"chat": chat_id or 68, "report": report_id or 74}


def dismiss_overlays(page: Page) -> None:
    page.evaluate("localStorage.setItem('fa_onboarding_done', '1')")
    for sel in ["button:has-text('知道了')", "button:has-text('跳过')", "button:has-text('关闭')"]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=400):
                btn.click()
                page.wait_for_timeout(200)
        except Exception:
            pass


def login_via_api(page: Page) -> None:
    resp = requests.post(
        f"{API_URL}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    user = data.get("user") or {}
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
    page.evaluate(
        """([token, username, isAdmin]) => {
          localStorage.setItem('token', token);
          localStorage.setItem('username', username);
          localStorage.setItem('is_admin', isAdmin);
          localStorage.setItem('fa_onboarding_done', '1');
        }""",
        [token, user.get("username", USERNAME), "1" if user.get("is_admin") else "0"],
    )


def capture_live() -> None:
    """可选：Playwright 实时截取（需前端能正常请求 API）。"""
    sessions = pick_sessions()
    print("Live sessions:", sessions)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=DEVICE_SCALE,
            locale="zh-CN",
        ).new_page()
        login_via_api(page)
        page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle")
        dismiss_overlays(page)
        page.screenshot(path=str(IMG_DIR / "01-dashboard.png"), type="png")
        browser.close()


def main() -> int:
    mode = os.environ.get("PROMO_MODE", "reference").lower()
    if mode == "live":
        IMG_DIR.mkdir(parents=True, exist_ok=True)
        capture_live()
        return 0

    synced = sync_reference_images()
    if not synced:
        print("No reference images synced.", file=sys.stderr)
        return 1

    print("\nImage sizes:")
    for p in sorted(IMG_DIR.glob("*.png")):
        with Image.open(p) as im:
            print(f"  {p.name}: {im.size[0]}x{im.size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
