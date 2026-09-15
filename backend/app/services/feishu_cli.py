"""通过 lark-cli 收发飞书 IM（bot 身份）。"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger("app.feishu_cli")

_SEND_LIMIT = 3500


def lark_cli_bin() -> str:
    path = shutil.which("lark-cli") or shutil.which("lark-cli.exe")
    if not path:
        raise RuntimeError("找不到 lark-cli，请先安装并确保在 PATH 里。")
    return path


def split_message(text: str, limit: int = _SEND_LIMIT) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        chunks.append(rest[:limit])
        rest = rest[limit:]
    return chunks


def build_text_content(text: str) -> str:
    """飞书 text 消息的 content JSON（单行）。换行写成 \\n，避免 Windows 命令行截断。"""
    return json.dumps({"text": text or ""}, ensure_ascii=False)


def send_markdown(chat_id: str, text: str, *, identity: str = "bot") -> None:
    """对外仍叫 markdown，实际发纯文本。飞书 post/markdown 会吞掉「标题：」后面的列表。"""
    if not chat_id:
        raise ValueError("chat_id required")
    from app.services.feishu_openapi import openapi_enabled, send_text

    if openapi_enabled():
        send_text(chat_id, text)
        return
    bin_path = lark_cli_bin()
    for chunk in split_message(text):
        content = build_text_content(chunk)
        cmd = [
            bin_path,
            "im",
            "+messages-send",
            "--as",
            identity,
            "--chat-id",
            chat_id,
            "--msg-type",
            "text",
            "--content",
            content,
        ]
        logger.info("feishu send chat=%s chars=%s", chat_id, len(chunk))
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-800:]
            raise RuntimeError(f"lark-cli send failed ({proc.returncode}): {err}")


def consume_messages(*, identity: str = "bot") -> Iterator[dict[str, Any]]:
    """阻塞读取 im.message.receive_v1，产出扁平事件 dict。"""
    bin_path = lark_cli_bin()
    cmd = [
        bin_path,
        "event",
        "consume",
        "im.message.receive_v1",
        "--as",
        identity,
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    ready = threading.Event()
    errors: list[str] = []

    def _stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip()
            if "[event] ready" in line:
                ready.set()
            if line:
                logger.info("lark-cli event: %s", line)
                if '"ok":false' in line.replace(" ", ""):
                    errors.append(line)

    threading.Thread(target=_stderr, daemon=True).start()
    if not ready.wait(45):
        proc.terminate()
        hint = errors[-1] if errors else "timeout waiting for [event] ready"
        raise RuntimeError(f"lark-cli event consume 未就绪：{hint}")

    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                logger.warning("skip non-json event line: %s", line[:200])
    finally:
        if proc.poll() is None:
            proc.terminate()
