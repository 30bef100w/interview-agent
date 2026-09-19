"""把简历画像拼成可挂笔记的结构化复盘树。"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

WHOLE_BULLET_MARKER = "__whole__"
MAX_NOTE_TEXT = 4000

_BULLET_LINE = re.compile(r"^[•·●○◦]\s*(.*)$|^[-–—*]\s+(.*)$")
_DATE_LINE = re.compile(r"^\d{4}[./年]\d{1,2}")
_URL_LINE = re.compile(r"^https?://", re.I)
_PARA_PREFIXES = ("负责项目", "我的职责", "项目背景", "项目描述")
_SECTION_STOP = (
    "教育背景",
    "教育经历",
    "实习经历",
    "工作经历",
    "项目经历",
    "项目经验",
    "专业技能",
    "技能特长",
    "校园经历",
    "自我评价",
    "荣誉奖项",
    "获奖情况",
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split())


def _compact(value: Any) -> str:
    return (
        _norm(value)
        .replace(" ", "")
        .replace("“", "")
        .replace("”", "")
        .replace('"', "")
        .replace("‘", "")
        .replace("’", "")
        .replace("（", "(")
        .replace("）", ")")
    )


def short_hash(raw: str) -> str:
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def make_item_key(section_type: str, identity: str) -> str:
    return short_hash(f"{section_type}|{_norm(identity)}")


def make_bullet_key(item: str, bullet_text: str, *, whole: bool = False) -> str:
    if whole:
        return short_hash(f"{item}|{WHOLE_BULLET_MARKER}")
    return short_hash(f"{item}|{_norm(bullet_text)}")


def project_identity(project: dict) -> str:
    return _norm(project.get("name")) or "未命名项目"


def experience_identity(exp: dict) -> str:
    parts = [_norm(exp.get("company")), _norm(exp.get("role")), _norm(exp.get("duration"))]
    return "|".join(p for p in parts if p) or "未命名经历"


def list_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _norm(item)
        if text:
            out.append(text)
    return out


def validate_note_payload(kind: str, question: str, answer: str, body: str) -> tuple[str, str, str]:
    kind = (kind or "").strip()
    q = _norm(question)[:MAX_NOTE_TEXT]
    a = (answer or "").strip()[:MAX_NOTE_TEXT]
    b = (body or "").strip()[:MAX_NOTE_TEXT]
    if kind == "qa":
        if not q:
            raise ValueError("问答对需要填写问题")
        return q, a, ""
    if kind == "note":
        if not b:
            raise ValueError("注释不能为空")
        return "", "", b
    raise ValueError("只支持问答对或注释")


def _join_wrap(left: str, right: str) -> str:
    if re.search(r"[A-Za-z0-9]$", left) and re.search(r"^[A-Za-z0-9]", right):
        return f"{left} {right}"
    return left + right


def split_resume_sections(raw_text: str) -> dict[str, str]:
    buckets: dict[str, list[str]] = {"intern": [], "project": [], "other": []}
    current = "other"
    for line in (raw_text or "").splitlines():
        key = line.strip().replace(" ", "")
        if key.startswith("实习经历") or key.startswith("工作经历"):
            current = "intern"
            continue
        if key.startswith("项目经历") or key.startswith("项目经验"):
            current = "project"
            continue
        if (
            key.startswith("教育背景")
            or key.startswith("教育经历")
            or key.startswith("专业技能")
            or key.startswith("自我评价")
        ):
            current = "other"
            continue
        buckets[current].append(line)
    return {name: "\n".join(lines) for name, lines in buckets.items()}


def _line_matches_title(line: str, title: str) -> bool:
    a, b = _compact(line), _compact(title)
    if not a or not b or len(b) < 2:
        return False
    return b in a or a in b


def slice_section_by_titles(section: str, titles: list[str]) -> dict[str, str]:
    ranked = sorted(
        {_norm(t) for t in titles if _norm(t)},
        key=lambda t: len(_compact(t)),
        reverse=True,
    )
    lines = (section or "").splitlines()
    marks: list[tuple[int, str]] = []
    used: set[str] = set()
    for i, line in enumerate(lines):
        for title in ranked:
            if title in used:
                continue
            if _line_matches_title(line, title):
                marks.append((i, title))
                used.add(title)
                break
    marks.sort()
    out: dict[str, str] = {}
    for idx, (start, title) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        out[title] = "\n".join(lines[start:end])
    return out


def extract_original_bullets(block: str) -> list[str]:
    """从一段原文里抽出完整 bullet（换行拼回），不改写成摘要。"""
    entries: list[str] = []
    current: str | None = None
    for raw_line in (block or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        compact = line.replace(" ", "")
        bullet_match = _BULLET_LINE.match(line)
        is_para = any(compact.startswith(p) for p in _PARA_PREFIXES)
        if bullet_match or is_para:
            if current:
                entries.append(_norm(current))
            if bullet_match:
                current = (bullet_match.group(1) or bullet_match.group(2) or "").strip()
            else:
                current = line
            continue
        if current:
            if (
                _DATE_LINE.match(line)
                or _URL_LINE.match(line)
                or any(compact.startswith(s) for s in _SECTION_STOP)
            ):
                entries.append(_norm(current))
                current = None
                continue
            current = _join_wrap(current, line)
    if current:
        entries.append(_norm(current))
    return [e for e in entries if len(e) >= 6]


def _note_out(note: dict) -> dict:
    return {
        "id": note["id"],
        "kind": note.get("kind") or "",
        "question": note.get("question") or "",
        "answer": note.get("answer") or "",
        "body": note.get("body") or "",
        "section_type": note.get("section_type") or "",
        "item_key": note.get("item_key") or "",
        "bullet_key": note.get("bullet_key") or "",
        "item_label": note.get("item_label") or "",
        "bullet_text": note.get("bullet_text") or "",
        "created_at": note.get("created_at"),
        "updated_at": note.get("updated_at"),
    }


def _build_item(
    *,
    section_type: str,
    identity: str,
    title: str,
    subtitle: str,
    meta: list[str],
    bullets_text: list[str],
    notes_by_bullet: dict[tuple[str, str], list[dict]],
    extra: dict | None = None,
) -> dict:
    ik = make_item_key(section_type, identity)
    bullets: list[dict] = [
        {
            "bullet_key": make_bullet_key(ik, "", whole=True),
            "text": "整段经历",
            "is_whole": True,
            "notes": [],
        }
    ]
    seen = {bullets[0]["bullet_key"]}
    for text in bullets_text:
        bk = make_bullet_key(ik, text)
        if bk in seen:
            continue
        seen.add(bk)
        bullets.append(
            {
                "bullet_key": bk,
                "text": text,
                "is_whole": False,
                "notes": [],
            }
        )
    for bullet in bullets:
        bullet["notes"] = [
            _note_out(n) for n in notes_by_bullet.get((ik, bullet["bullet_key"]), [])
        ]
    orphans: list[dict] = []
    for (item_k, b_k), group in notes_by_bullet.items():
        if item_k == ik and b_k not in seen:
            orphans.extend(_note_out(n) for n in group)
    payload = {
        "section_type": section_type,
        "item_key": ik,
        "title": title,
        "subtitle": subtitle,
        "meta": meta,
        "bullets": bullets,
        "orphan_notes": orphans,
    }
    if extra:
        payload.update(extra)
    return payload


def assemble_review_tree(
    profile: dict | None,
    notes: list[dict],
    raw_text: str | None = None,
) -> dict:
    profile = profile if isinstance(profile, dict) else {}
    notes_by_bullet: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for note in notes:
        notes_by_bullet[(note.get("item_key") or "", note.get("bullet_key") or "")].append(note)

    sections = split_resume_sections(raw_text or "")
    intern_titles = [
        _norm(exp.get("company"))
        for exp in (profile.get("experience") or [])
        if isinstance(exp, dict) and _norm(exp.get("company"))
    ]
    intern_slices = slice_section_by_titles(sections.get("intern") or "", intern_titles)
    project_titles = [
        _norm(proj.get("name"))
        for proj in (profile.get("projects") or [])
        if isinstance(proj, dict) and _norm(proj.get("name"))
    ]
    project_slices = slice_section_by_titles(sections.get("project") or "", project_titles)

    experience_items: list[dict] = []
    for exp in profile.get("experience") or []:
        if not isinstance(exp, dict):
            continue
        identity = experience_identity(exp)
        title = _norm(exp.get("company")) or "未标注公司"
        subtitle = " · ".join(
            x for x in (_norm(exp.get("role")), _norm(exp.get("duration"))) if x
        )
        original = extract_original_bullets(intern_slices.get(title, ""))
        experience_items.append(
            _build_item(
                section_type="experience",
                identity=identity,
                title=title,
                subtitle=subtitle,
                meta=[],
                bullets_text=original or list_str(exp.get("responsibilities")),
                notes_by_bullet=notes_by_bullet,
            )
        )

    project_items: list[dict] = []
    has_project_section = bool((sections.get("project") or "").strip())
    for proj in profile.get("projects") or []:
        if not isinstance(proj, dict):
            continue
        identity = project_identity(proj)
        title = _norm(proj.get("name")) or "未命名项目"
        original_block = project_slices.get(title, "")
        if has_project_section and title not in project_slices:
            continue
        original = extract_original_bullets(original_block)
        project_items.append(
            _build_item(
                section_type="project",
                identity=identity,
                title=title,
                subtitle=_norm(proj.get("role")),
                meta=[],
                bullets_text=original or list_str(proj.get("highlights")),
                notes_by_bullet=notes_by_bullet,
            )
        )

    known_item_keys = {it["item_key"] for it in experience_items + project_items}
    unmatched = [
        _note_out(note)
        for note in notes
        if (note.get("item_key") or "") not in known_item_keys
    ]

    education: list[dict] = []
    for ed in profile.get("education") or []:
        if not isinstance(ed, dict):
            continue
        education.append(
            {
                "school": _norm(ed.get("school")),
                "degree": _norm(ed.get("degree")),
                "major": _norm(ed.get("major")),
                "year": _norm(ed.get("year")),
            }
        )

    return {
        "name": _norm(profile.get("name")),
        "experience_years": _norm(profile.get("experience_years")),
        "education": education,
        "skills": list_str(profile.get("skills")),
        "experience": experience_items,
        "projects": project_items,
        "unmatched_notes": unmatched,
    }
