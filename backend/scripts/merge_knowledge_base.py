# -*- coding: utf-8 -*-
"""合并 GitHub（structured.jsonl）与知乎（zhihu_qa_priority_A.jsonl）题库。

会先备份当前 questions_dedup 与 GitHub structured 到 knowledge_base/backups/，
再写出合并后的 questions_dedup.jsonl（保留各自真实 roles，不强制 agent_dev）。
"""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KB = Path(__file__).resolve().parents[1] / "data" / "knowledge_base"
BACKUPS = KB / "backups"

GITHUB_SRC = KB / "structured.jsonl"
ZHIHU_SRC = ROOT / "data" / "processed" / "zhihu_qa_priority_A.jsonl"
OUT = KB / "questions_dedup.jsonl"
META = KB / "questions_dedup.meta.json"

KEEP_KEYS = (
    "question",
    "answer",
    "category",
    "company",
    "roles",
    "business_scene",
    "tech_scene",
    "era",
    "source_repo",
    "source_file",
    "source_url",
    "source_keyword",
    "priority",
    "source_batch",
)


def _norm(s: str) -> str:
    return re.sub(r"\W+", "", (s or "").lower())


def dedup_key(row: dict) -> tuple:
    return (_norm(row.get("question")), _norm(row.get("answer")), row.get("category"))


def _batch_set(row: dict) -> set[str]:
    raw = row.get("source_batch") or ""
    return {p for p in str(raw).split("+") if p}


def pick_row(existing: dict, incoming: dict) -> dict:
    """同键冲突：合并 roles，优先保留有答案、场景更全的一条。"""
    out = dict(existing)
    for k in KEEP_KEYS:
        if k in incoming and incoming[k] not in (None, "", []):
            if k == "roles":
                merged = sorted(set(existing.get("roles") or []) | set(incoming.get("roles") or []))
                out["roles"] = merged
            elif k == "answer":
                if len(str(incoming.get("answer") or "")) > len(str(existing.get("answer") or "")):
                    out["answer"] = incoming["answer"]
            elif k in ("business_scene", "tech_scene"):
                out[k] = sorted(set(existing.get(k) or []) | set(incoming.get(k) or []))
            elif k == "source_batch":
                continue
            elif not existing.get(k):
                out[k] = incoming[k]
    batches = sorted(_batch_set(existing) | _batch_set(incoming))
    if batches:
        out["source_batch"] = "+".join(batches)
    return out


def normalize_github(row: dict) -> dict:
    out = {k: row.get(k) for k in KEEP_KEYS if k in row}
    out["source_batch"] = "github"
    if not out.get("source_repo"):
        out["source_repo"] = "facejing"
    out.setdefault("business_scene", [])
    out.setdefault("tech_scene", [])
    out.setdefault("roles", [])
    return out


def normalize_zhihu(row: dict) -> dict:
    out = {k: row.get(k) for k in KEEP_KEYS if k in row}
    out["source_batch"] = "zhihu"
    if not out.get("source_repo"):
        out["source_repo"] = "zhihu"
    out.setdefault("business_scene", [])
    out.setdefault("tech_scene", [])
    out.setdefault("roles", [])
    return out


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def backup_files() -> dict[str, str]:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    copied: dict[str, str] = {}

    if OUT.exists():
        dst = BACKUPS / f"zhihu_only_questions_dedup_{stamp}.jsonl"
        shutil.copy2(OUT, dst)
        copied["zhihu_dedup"] = str(dst)
    meta_old = KB / "questions_dedup.meta.json"
    if meta_old.exists():
        dst = BACKUPS / f"zhihu_only_questions_dedup_{stamp}.meta.json"
        shutil.copy2(meta_old, dst)
        copied["zhihu_meta"] = str(dst)
    if GITHUB_SRC.exists():
        dst = BACKUPS / f"github_structured_{stamp}.jsonl"
        shutil.copy2(GITHUB_SRC, dst)
        copied["github_structured"] = str(dst)
    return copied


def dedup_source_rows(name: str, rows: list[dict]) -> tuple[list[dict], int]:
    """源内先去重，避免知乎重跑叠行把统计弄脏。"""
    out: dict[tuple, dict] = {}
    skipped = 0
    for raw in rows:
        row = normalize_github(raw) if name == "github" else normalize_zhihu(raw)
        q = str(row.get("question") or "").strip()
        if not q:
            continue
        key = dedup_key(row)
        if key in out:
            out[key] = pick_row(out[key], row)
            skipped += 1
        else:
            out[key] = row
    return list(out.values()), skipped


def merge_rows(sources: list[tuple[str, list[dict]]]) -> tuple[list[dict], dict]:
    merged: dict[tuple, dict] = {}
    stats: dict = {
        "by_source_raw": {},
        "by_source_deduped": {},
        "duplicates_skipped": 0,
        "cross_source_merged": 0,
    }
    prepared: list[tuple[str, list[dict]]] = []
    for name, rows in sources:
        stats["by_source_raw"][name] = len(rows)
        deduped, inner_skipped = dedup_source_rows(name, rows)
        stats["by_source_deduped"][name] = len(deduped)
        stats["duplicates_skipped"] += inner_skipped
        prepared.append((name, deduped))

    for name, rows in prepared:
        for row in rows:
            key = dedup_key(row)
            if key in merged:
                prev_batches = _batch_set(merged[key])
                merged[key] = pick_row(merged[key], row)
                new_batches = _batch_set(merged[key])
                if len(new_batches) > len(prev_batches):
                    stats["cross_source_merged"] += 1
                else:
                    stats["duplicates_skipped"] += 1
            else:
                merged[key] = row
    return list(merged.values()), stats


def main() -> None:
    if not GITHUB_SRC.exists():
        raise SystemExit(f"缺少 GitHub 结构化题库: {GITHUB_SRC}")
    if not ZHIHU_SRC.exists():
        raise SystemExit(f"缺少知乎源文件: {ZHIHU_SRC}")

    backups = backup_files()
    github_rows = load_jsonl(GITHUB_SRC)
    zhihu_rows = load_jsonl(ZHIHU_SRC)

    merged, merge_stats = merge_rows([("github", github_rows), ("zhihu", zhihu_rows)])

    role_counter: Counter = Counter()
    batch_counter: Counter = Counter()
    cat_counter: Counter = Counter()
    for row in merged:
        cat_counter[row.get("category") or "?"] += 1
        batch_counter[row.get("source_batch") or "?"] += 1
        for r in row.get("roles") or []:
            role_counter[r] += 1

    with OUT.open("w", encoding="utf-8") as f:
        for row in merged:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    meta = {
        "merged_at": datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "github": str(GITHUB_SRC),
            "zhihu": str(ZHIHU_SRC),
        },
        "backups": backups,
        "written": len(merged),
        "roles_forced": None,
        "by_category": dict(cat_counter),
        "by_source_batch": dict(batch_counter),
        "top_roles": role_counter.most_common(15),
        **merge_stats,
    }
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
