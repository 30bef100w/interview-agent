from pathlib import Path

import pytest

QUESTION_BANK = (
    Path(__file__).resolve().parents[1] / "data" / "knowledge_base" / "questions_dedup.jsonl"
)


def has_question_bank() -> bool:
    return QUESTION_BANK.is_file() and QUESTION_BANK.stat().st_size > 1024


requires_question_bank = pytest.mark.skipif(
    not has_question_bank(),
    reason="questions_dedup.jsonl 不随仓库分发，GitHub CI 跳过依赖题库的用例",
)
