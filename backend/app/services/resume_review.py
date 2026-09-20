"""把简历画像拼成可挂笔记的结构化复盘树，并支持手工增删项目 / bullet。"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import defaultdict
from typing import Any

WHOLE_BULLET_MARKER = "__whole__"
MAX_NOTE_TEXT = 4000
MAX_BULLET_TEXT = 4000
MAX_TITLE = 256

_BULLET_LINE = re.compile(r"^[•·●○◦]\s*(.*)$|^[-–—*]\s+(.*)$")
_DATE_LINE = re.compile(r"^\d{4}[./年]\d{1,2}")
_URL_LINE = re.compile(r"^https?://", re.I)
_QUOTED_NAME = re.compile(r'[“"「『](.+?)[”"」』]')
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


def new_item_key() -> str:
    return short_hash(f"manual|{uuid.uuid4()}")


def new_bullet_key() -> str:
    return short_hash(f"manual-b|{uuid.uuid4()}")


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


def extract_project_title_from_para(para: str) -> str:
    rest = re.sub(r"^负责项目\s*[：:]", "", para).strip()
    quoted = _QUOTED_NAME.search(rest)
    if quoted:
        title = _norm(quoted.group(1))
        if title:
            return title[:MAX_TITLE]
    cut = re.split(r"[是，,。]", rest, maxsplit=1)[0]
    title = _norm(cut)
    return (title or "未命名项目")[:MAX_TITLE]


def split_intern_projects(block: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """一段实习里按「负责项目」切开：前导 bullet + [(项目名, bullets)...]。"""
    leading: list[str] = []
    groups: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_bullets: list[str] = []
    for text in extract_original_bullets(block):
        compact = text.replace(" ", "")
        if compact.startswith("负责项目"):
            if current_title is not None:
                groups.append((current_title, current_bullets))
            elif current_bullets:
                leading.extend(current_bullets)
            current_title = extract_project_title_from_para(text)
            current_bullets = [text]
            continue
        if current_title is None:
            leading.append(text)
        else:
            current_bullets.append(text)
    if current_title is not None:
        groups.append((current_title, current_bullets))
    return leading, groups


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


def _whole_bullet(item_key: str) -> dict:
    return {
        "bullet_key": make_bullet_key(item_key, "", whole=True),
        "text": "整段经历",
        "is_whole": True,
        "notes": [],
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
    bullets: list[dict] = [_whole_bullet(ik)]
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
        "scene_tags": [],
        "bullets": bullets,
        "orphan_notes": orphans,
        "children": [],
    }
    if extra:
        payload.update(extra)
    return payload


def _collect_item_keys(items: list[dict]) -> set[str]:
    keys: set[str] = set()
    for item in items:
        keys.add(item.get("item_key") or "")
        keys |= _collect_item_keys(item.get("children") or [])
    keys.discard("")
    return keys


def _education_from_profile(profile: dict) -> list[dict]:
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
    return education


def _notes_index(notes: list[dict]) -> dict[tuple[str, str], list[dict]]:
    notes_by_bullet: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for note in notes:
        notes_by_bullet[(note.get("item_key") or "", note.get("bullet_key") or "")].append(note)
    return notes_by_bullet


def assemble_review_tree(
    profile: dict | None,
    notes: list[dict],
    raw_text: str | None = None,
) -> dict:
    profile = profile if isinstance(profile, dict) else {}
    notes_by_bullet = _notes_index(notes)

    sections = split_resume_sections(raw_text or "")
    intern_titles = [
        _norm(exp.get("company"))
        for exp in (profile.get("experience") or [])
        if isinstance(exp, dict) and _norm(exp.get("company"))
    ]
    intern_slices = slice_section_by_titles(sections.get("intern") or "", intern_titles)
    if not intern_slices and len(intern_titles) == 1:
        intern_slices = {intern_titles[0]: sections.get("intern") or ""}
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
        block = intern_slices.get(title, "")
        leading, groups = split_intern_projects(block)
        children = []
        used_child_titles: set[str] = set()
        for idx, (ptitle, pbullets) in enumerate(groups):
            child_title = ptitle
            if child_title in used_child_titles:
                child_title = f"{ptitle} ({idx + 1})"
            used_child_titles.add(child_title)
            children.append(
                _build_item(
                    section_type="project",
                    identity=f"{identity}|{child_title}",
                    title=child_title,
                    subtitle="",
                    meta=[],
                    bullets_text=pbullets,
                    notes_by_bullet=notes_by_bullet,
                )
            )
        intern_bullets = leading
        if not groups:
            intern_bullets = leading or list_str(exp.get("responsibilities"))
        experience_items.append(
            _build_item(
                section_type="experience",
                identity=identity,
                title=title,
                subtitle=subtitle,
                meta=[],
                bullets_text=intern_bullets,
                notes_by_bullet=notes_by_bullet,
                extra={"children": children},
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

    known_item_keys = _collect_item_keys(experience_items + project_items)
    unmatched = [
        _note_out(note)
        for note in notes
        if (note.get("item_key") or "") not in known_item_keys
    ]

    return {
        "name": _norm(profile.get("name")),
        "experience_years": _norm(profile.get("experience_years")),
        "education": _education_from_profile(profile),
        "skills": list_str(profile.get("skills")),
        "experience": experience_items,
        "projects": project_items,
        "unmatched_notes": unmatched,
    }


def dump_layout(tree: dict) -> dict:
    def dump_item(item: dict) -> dict:
        return {
            "section_type": item.get("section_type") or "project",
            "item_key": item.get("item_key") or new_item_key(),
            "title": item.get("title") or "",
            "subtitle": item.get("subtitle") or "",
            "bullets": [
                {
                    "bullet_key": b.get("bullet_key") or new_bullet_key(),
                    "text": b.get("text") or "",
                    "is_whole": bool(b.get("is_whole")),
                }
                for b in (item.get("bullets") or [])
                if isinstance(b, dict)
            ],
            "children": [
                dump_item(child)
                for child in (item.get("children") or [])
                if isinstance(child, dict)
            ],
        }

    return {
        "experience": [
            dump_item(item) for item in (tree.get("experience") or []) if isinstance(item, dict)
        ],
        "projects": [
            dump_item(item) for item in (tree.get("projects") or []) if isinstance(item, dict)
        ],
    }


def _normalize_layout_item(raw: dict, default_type: str) -> dict:
    bullets: list[dict] = []
    seen: set[str] = set()
    for bullet in raw.get("bullets") or []:
        if not isinstance(bullet, dict):
            continue
        key = (bullet.get("bullet_key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        bullets.append(
            {
                "bullet_key": key[:32],
                "text": (bullet.get("text") or "")[:MAX_BULLET_TEXT],
                "is_whole": bool(bullet.get("is_whole")),
            }
        )
    item_key = (raw.get("item_key") or "").strip() or new_item_key()
    if not any(b.get("is_whole") for b in bullets):
        bullets.insert(0, _whole_bullet(item_key))
        bullets[0].pop("notes", None)
    return {
        "section_type": (raw.get("section_type") or default_type),
        "item_key": item_key[:32],
        "title": (_norm(raw.get("title")) or "未命名")[:MAX_TITLE],
        "subtitle": _norm(raw.get("subtitle"))[:MAX_TITLE],
        "bullets": bullets,
        "children": [
            _normalize_layout_item(child, "project")
            for child in (raw.get("children") or [])
            if isinstance(child, dict)
        ],
    }


def parse_layout(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "experience": [
            _normalize_layout_item(item, "experience")
            for item in (raw.get("experience") or [])
            if isinstance(item, dict)
        ],
        "projects": [
            _normalize_layout_item(item, "project")
            for item in (raw.get("projects") or [])
            if isinstance(item, dict)
        ],
    }


def _hydrate_item(item: dict, notes_by_bullet: dict[tuple[str, str], list[dict]]) -> dict:
    ik = item["item_key"]
    seen = {b["bullet_key"] for b in item.get("bullets") or []}
    bullets = []
    for bullet in item.get("bullets") or []:
        bullets.append(
            {
                "bullet_key": bullet["bullet_key"],
                "text": bullet.get("text") or "",
                "is_whole": bool(bullet.get("is_whole")),
                "notes": [
                    _note_out(n)
                    for n in notes_by_bullet.get((ik, bullet["bullet_key"]), [])
                ],
            }
        )
    orphans: list[dict] = []
    for (item_k, b_k), group in notes_by_bullet.items():
        if item_k == ik and b_k not in seen:
            orphans.extend(_note_out(n) for n in group)
    return {
        "section_type": item.get("section_type") or "project",
        "item_key": ik,
        "title": item.get("title") or "",
        "subtitle": item.get("subtitle") or "",
        "meta": [],
        "scene_tags": [],
        "bullets": bullets,
        "orphan_notes": orphans,
        "children": [
            _hydrate_item(child, notes_by_bullet) for child in (item.get("children") or [])
        ],
    }


def hydrate_layout(layout: dict, notes: list[dict], profile: dict | None) -> dict:
    profile = profile if isinstance(profile, dict) else {}
    notes_by_bullet = _notes_index(notes)
    layout = parse_layout(layout)
    experience_items = [_hydrate_item(item, notes_by_bullet) for item in layout["experience"]]
    project_items = [_hydrate_item(item, notes_by_bullet) for item in layout["projects"]]
    known = _collect_item_keys(experience_items + project_items)
    unmatched = [
        _note_out(note)
        for note in notes
        if (note.get("item_key") or "") not in known
    ]
    return {
        "name": _norm(profile.get("name")),
        "experience_years": _norm(profile.get("experience_years")),
        "education": _education_from_profile(profile),
        "skills": list_str(profile.get("skills")),
        "experience": experience_items,
        "projects": project_items,
        "unmatched_notes": unmatched,
    }


def find_item(layout: dict, item_key: str) -> tuple[list[dict], int, dict | None]:
    def search(items: list[dict], parent: dict | None):
        for idx, item in enumerate(items):
            if item.get("item_key") == item_key:
                return items, idx, parent
            found = search(item.get("children") or [], item)
            if found is not None:
                return found
        return None

    for section in ("experience", "projects"):
        found = search(layout.get(section) or [], None)
        if found is not None:
            return found
    raise KeyError(item_key)


def empty_item(section_type: str, title: str, subtitle: str = "") -> dict:
    item_key = new_item_key()
    return {
        "section_type": section_type,
        "item_key": item_key,
        "title": (_norm(title) or "未命名")[:MAX_TITLE],
        "subtitle": _norm(subtitle)[:MAX_TITLE],
        "bullets": [
            {
                "bullet_key": make_bullet_key(item_key, "", whole=True),
                "text": "整段经历",
                "is_whole": True,
            }
        ],
        "children": [],
    }


def add_review_item(
    layout: dict,
    *,
    title: str,
    section: str,
    parent_item_key: str | None = None,
    subtitle: str = "",
) -> dict:
    title = _norm(title)
    if not title:
        raise ValueError("项目名称不能为空")
    if parent_item_key:
        siblings, idx, parent_of_parent = find_item(layout, parent_item_key)
        parent = siblings[idx]
        if parent_of_parent is not None:
            raise ValueError("子项目下面不能再嵌套项目")
        if parent.get("section_type") != "experience":
            raise ValueError("只能在实习经历下添加子项目")
        child = empty_item("project", title, subtitle)
        parent.setdefault("children", []).append(child)
        return child
    if section == "experience":
        item = empty_item("experience", title, subtitle)
        layout.setdefault("experience", []).append(item)
        return item
    if section != "projects":
        raise ValueError("section 只能是 experience 或 projects")
    item = empty_item("project", title, subtitle)
    layout.setdefault("projects", []).append(item)
    return item


def delete_review_item(layout: dict, item_key: str) -> None:
    siblings, idx, _parent = find_item(layout, item_key)
    siblings.pop(idx)


def rename_review_item(
    layout: dict,
    item_key: str,
    title: str | None = None,
    subtitle: str | None = None,
) -> None:
    siblings, idx, _parent = find_item(layout, item_key)
    if title is not None:
        cleaned = _norm(title)
        if not cleaned:
            raise ValueError("名称不能为空")
        siblings[idx]["title"] = cleaned[:MAX_TITLE]
    if subtitle is not None:
        siblings[idx]["subtitle"] = _norm(subtitle)[:MAX_TITLE]


def add_review_bullet(layout: dict, item_key: str, text: str) -> dict:
    text = _norm(text)
    if not text:
        raise ValueError("bullet 不能为空")
    siblings, idx, _parent = find_item(layout, item_key)
    bullet = {
        "bullet_key": new_bullet_key(),
        "text": text[:MAX_BULLET_TEXT],
        "is_whole": False,
    }
    siblings[idx].setdefault("bullets", []).append(bullet)
    return bullet


def update_review_bullet(layout: dict, item_key: str, bullet_key: str, text: str) -> None:
    text = _norm(text)
    if not text:
        raise ValueError("bullet 不能为空")
    siblings, idx, _parent = find_item(layout, item_key)
    for bullet in siblings[idx].get("bullets") or []:
        if bullet.get("bullet_key") == bullet_key:
            if bullet.get("is_whole"):
                raise ValueError("整段经历不能改成正文")
            bullet["text"] = text[:MAX_BULLET_TEXT]
            return
    raise KeyError(bullet_key)


def delete_review_bullet(layout: dict, item_key: str, bullet_key: str) -> None:
    siblings, idx, _parent = find_item(layout, item_key)
    bullets = siblings[idx].get("bullets") or []
    for i, bullet in enumerate(bullets):
        if bullet.get("bullet_key") == bullet_key:
            if bullet.get("is_whole"):
                raise ValueError("整段经历不能删除")
            bullets.pop(i)
            return
    raise KeyError(bullet_key)
