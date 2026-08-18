from pathlib import Path

import pymupdf

from app.prompts.resume import PROFILE_SYSTEM
from app.services.llm.client import OpenAiLlm

_llm = OpenAiLlm()


def extract_text(pdf_path: Path) -> str:
    doc = pymupdf.open(pdf_path)
    try:
        return "\n".join(page.get_text() for page in doc).strip()
    finally:
        doc.close()


def build_profile(raw_text: str) -> dict:
    return _llm.chat_json(PROFILE_SYSTEM, f"以下是候选人简历原文，请提取画像：\n\n{raw_text[:12000]}")
