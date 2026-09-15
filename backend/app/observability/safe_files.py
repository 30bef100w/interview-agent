"""日志目录写入失败时静默跳过，避免把面试主流程打崩。"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("app.trace")


def mkdir_soft(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        logger.warning("skip mkdir %s", path)
        return False


def write_text_soft(path: Path, text: str) -> bool:
    if not mkdir_soft(path.parent):
        return False
    try:
        path.write_text(text, encoding="utf-8")
        return True
    except OSError:
        logger.warning("skip write %s", path)
        return False


def append_text_soft(path: Path, text: str) -> bool:
    if not mkdir_soft(path.parent):
        return False
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(text)
        return True
    except OSError:
        logger.warning("skip append %s", path)
        return False
