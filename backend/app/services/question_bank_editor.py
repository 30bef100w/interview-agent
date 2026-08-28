"""题库文件编辑：按 question_norm 查找 / 改标签 / 删除，并刷新内存缓存。"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KB = Path(__file__).resolve().parents[2] / "data" / "knowledge_base"
QUESTIONS_PATH = KB / "questions_dedup.jsonl"
BACKUP_DIR = KB / "backups"


def question_norm(text: str) -> str:
    return re.sub(r"\W+", "", (text or "").lower())


def invalidate_question_cache() -> None:
    from app.services.knowledge_retrieval import load_questions

    load_questions.cache_clear()


def _load_all() -> list[dict]:
    if not QUESTIONS_PATH.exists():
        return []
    rows: list[dict] = []
    with open(QUESTIONS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def backup_questions_file() -> Path | None:
    if not QUESTIONS_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"questions_dedup_{stamp}.jsonl"
    shutil.copy2(QUESTIONS_PATH, dst)
    return dst


def _save_all(questions: list[dict]) -> None:
    KB.mkdir(parents=True, exist_ok=True)
    backup_questions_file()
    tmp = QUESTIONS_PATH.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    tmp.replace(QUESTIONS_PATH)
    invalidate_question_cache()


def find_question(q_norm: str) -> dict | None:
    if not q_norm:
        return None
    for q in _load_all():
        if question_norm(q.get("question") or "") == q_norm:
            return q
    return None


def update_question(q_norm: str, patch: dict[str, Any]) -> dict:
    if not q_norm:
        raise ValueError("question_norm 为空")
    questions = _load_all()
    if not questions:
        raise FileNotFoundError("题库文件不存在或为空")
    found = False
    updated: dict | None = None
    allowed = {"roles", "business_scene", "tech_scene", "company", "category"}
    for q in questions:
        if question_norm(q.get("question") or "") != q_norm:
            continue
        found = True
        for key, value in patch.items():
            if key not in allowed:
                continue
            if key == "company":
                q["company"] = value or None
            else:
                q[key] = value
        updated = q
        break
    if not found or updated is None:
        raise LookupError("题库中未找到该题目")
    _save_all(questions)
    return updated


def delete_question(q_norm: str) -> int:
    if not q_norm:
        raise ValueError("question_norm 为空")
    questions = _load_all()
    if not questions:
        raise FileNotFoundError("题库文件不存在或为空")
    kept = [q for q in questions if question_norm(q.get("question") or "") != q_norm]
    removed = len(questions) - len(kept)
    if removed == 0:
        raise LookupError("题库中未找到该题目")
    _save_all(kept)
    return removed


def load_scene_catalog() -> dict:
    scenes_path = Path(__file__).resolve().parents[2] / "data" / "project_scenes.json"
    with open(scenes_path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        "business_scenes": data.get("business_scenes") or [],
        "tech_scenes": data.get("tech_scenes") or [],
    }
