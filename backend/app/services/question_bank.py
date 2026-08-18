"""题库服务：读本地题库 JSON，为面试随机选题、查询题面。纯本地，不依赖网络。"""
import json
import random
import re
from pathlib import Path

HOT100_PATH = Path(__file__).resolve().parents[2] / "data" / "hot100.json"
PROBLEMS_PATH = Path(__file__).resolve().parents[2] / "data" / "coding_problems.json"

_hot100: list[dict] | None = None
_problems: dict | None = None


def _load_hot100() -> list[dict]:
    global _hot100
    if _hot100 is None:
        if HOT100_PATH.exists():
            _hot100 = json.loads(HOT100_PATH.read_text("utf-8"))
        else:
            _hot100 = []
    return _hot100


def _load_problems() -> dict:
    global _problems
    if _problems is None:
        if PROBLEMS_PATH.exists():
            _problems = json.loads(PROBLEMS_PATH.read_text("utf-8"))
        else:
            _problems = {}
    return _problems


_ALLOWED_TAGS = {
    "p", "pre", "code", "strong", "em", "b", "i", "u",
    "ul", "ol", "li", "br", "sup", "sub", "span", "div",
}


def sanitize_problem_html(html: str) -> str:
    """白名单清洗力扣题面 HTML，供前端直接渲染。"""
    if not html:
        return ""
    html = re.sub(r"<(script|style|iframe|object|embed)[^>]*>[\s\S]*?</\1>", "", html, flags=re.I)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    def _keep(m: re.Match) -> str:
        raw = m.group(0)
        if raw.startswith("</"):
            name = raw[2:-1].strip().lower()
            return f"</{name}>" if name in _ALLOWED_TAGS else ""
        name_m = re.match(r"<(\w+)", raw)
        if not name_m:
            return ""
        name = name_m.group(1).lower()
        if name not in _ALLOWED_TAGS:
            return ""
        if name == "br":
            return "<br/>"
        return f"<{name}>"

    html = re.sub(r"</?[a-zA-Z][^>]*>", _keep, html)
    # 段落内：code 两侧的换行压成空格，避免窄屏看起来像「乱换行」
    html = re.sub(r"\s*(<code>)", r" \1", html)
    html = re.sub(r"(</code>)\s*", r"\1 ", html)
    html = re.sub(r"(<p>)\s+", r"\1", html)
    html = re.sub(r"\s+(</p>)", r"\1", html)
    # pre 内保留换行：上面全局替换可能影响 pre，再把 pre 块里多余首尾空格收一下即可
    html = re.sub(r"[ \t]{2,}", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def html_to_text(html: str) -> str:
    """题面 HTML → 纯文本，保留段落/列表换行（兼容旧字段）。"""
    text = re.sub(r"</p\s*>", "\n\n", html, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.I)
    text = re.sub(r"</?(pre|code)[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    for entity, ch in (
        ("&nbsp;", " "),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&amp;", "&"),
        ("&quot;", '"'),
        ("&#39;", "'"),
    ):
        text = text.replace(entity, ch)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def pick_coding_question(
    difficulty: str | None = None, exclude_slugs: set[str] | None = None
) -> dict | None:
    """随机选一道已配置对拍的题；difficulty 可为 Easy/Medium/Hard 过滤。"""
    problems = _load_problems()
    if not problems:
        return None
    hot100 = {q["slug"]: q for q in _load_hot100()}
    exclude = exclude_slugs or set()
    pool = [slug for slug in problems if slug in hot100 and slug not in exclude]
    if difficulty:
        pool = [s for s in pool if hot100[s]["difficulty"] == difficulty]
    if not pool:
        pool = [s for s in problems if s not in exclude] or list(problems)
    if not pool:
        return None
    slug = random.choice(pool)
    return build_problem_view(slug)


def build_problem_view(slug: str) -> dict | None:
    """slug → 前端需要的完整题目视图（题面 + 示例 + 模板）。"""
    problems = _load_problems()
    hot100 = {q["slug"]: q for q in _load_hot100()}
    cfg = problems.get(slug)
    meta = hot100.get(slug)
    if not cfg or not meta:
        return None
    from app.services.code_lang import (
        IO_HINT,
        LANG_META,
        SCRATCH_FILENAME,
        SUPPORTED_LANGS,
        build_templates,
    )
    from app.services.code_runner import available_languages

    examples = []
    for ex in cfg["examples"]:
        examples.append({"args": ex["args"], "expected": ex["expected"]})
    templates_fn = build_templates(cfg, mode="function")
    templates_sc = build_templates(cfg, mode="scratch")
    ready = available_languages()
    raw_html = meta.get("description_html") or ""
    return {
        "slug": slug,
        "title": meta["title_cn"],
        "difficulty": meta["difficulty"],
        "tags": meta.get("tags_cn", []),
        "description": html_to_text(raw_html),
        "description_html": sanitize_problem_html(raw_html),
        "method": cfg["method"],
        "params": cfg["params"],
        "template": templates_fn["python"],  # 兼容旧前端
        "templates": {k: templates_fn[k] for k in SUPPORTED_LANGS},
        "templates_by_mode": {
            "function": {k: templates_fn[k] for k in SUPPORTED_LANGS},
            "scratch": {k: templates_sc[k] for k in SUPPORTED_LANGS},
        },
        "io_hint": IO_HINT,
        "languages": [
            {
                "id": lang,
                "label": LANG_META[lang]["label"],
                "monaco": LANG_META[lang]["monaco"],
                "filename": LANG_META[lang]["filename"],
                "filename_scratch": SCRATCH_FILENAME[lang],
                "available": lang in ready,
            }
            for lang in SUPPORTED_LANGS
        ],
        "examples": examples,
    }
