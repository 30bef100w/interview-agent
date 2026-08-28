"""题库编辑服务单测。"""
import json
from pathlib import Path

import pytest

from app.services import question_bank_editor as qbe


@pytest.fixture
def kb_tmp(monkeypatch, tmp_path):
    kb = tmp_path / "knowledge_base"
    kb.mkdir()
    qfile = kb / "questions_dedup.jsonl"
    rows = [
        {
            "question": "JVM 垃圾回收器有哪些？",
            "roles": ["java_backend"],
            "business_scene": [],
            "tech_scene": [],
            "category": "bagu",
            "company": None,
        },
        {
            "question": "Agent 的核心架构是什么？",
            "roles": ["agent_dev"],
            "business_scene": ["ai_app"],
            "tech_scene": ["ai_rag"],
            "category": "bagu",
            "company": "bytedance",
        },
    ]
    with open(qfile, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    scenes = tmp_path / "project_scenes.json"
    scenes.write_text(
        json.dumps({"business_scenes": [], "tech_scenes": []}),
        encoding="utf-8",
    )

    monkeypatch.setattr(qbe, "QUESTIONS_PATH", qfile)
    monkeypatch.setattr(qbe, "BACKUP_DIR", kb / "backups")
    monkeypatch.setattr(qbe, "KB", kb)
    return qfile


def test_find_and_update_question(kb_tmp):
    norm = qbe.question_norm("JVM 垃圾回收器有哪些？")
    found = qbe.find_question(norm)
    assert found is not None
    updated = qbe.update_question(
        norm,
        {"roles": ["agent_dev", "java_backend"], "category": "project"},
    )
    assert updated["roles"] == ["agent_dev", "java_backend"]
    assert updated["category"] == "project"
    reloaded = qbe.find_question(norm)
    assert reloaded["roles"] == ["agent_dev", "java_backend"]


def test_delete_question(kb_tmp):
    norm = qbe.question_norm("Agent 的核心架构是什么？")
    removed = qbe.delete_question(norm)
    assert removed == 1
    assert qbe.find_question(norm) is None
    remaining = qbe._load_all()
    assert len(remaining) == 1


def test_backup_on_save(kb_tmp):
    norm = qbe.question_norm("JVM 垃圾回收器有哪些？")
    qbe.update_question(norm, {"roles": ["agent_dev"]})
    backups = list(qbe.BACKUP_DIR.glob("*.jsonl"))
    assert backups
