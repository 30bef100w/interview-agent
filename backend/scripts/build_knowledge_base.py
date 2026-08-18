"""面经数据清洗与打标：16 个仓库 md → data/knowledge_base/（JSONL + meta 报告）。

流程：文件筛选 → 内容类型判定（真题/面经/知识体系/教程/杂项）→ 大分类（项目/八股）
→ 打标（企业/岗位/场景，非必选）→ 分块 → 去重 → 输出 JSONL。
规则层先行，LLM 精结构化是下一步。
"""
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.job_roles import infer_company, infer_roles  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]  # 项目根
SRC = _ROOT / "data" / "facejing_src"
OUT = Path(__file__).resolve().parents[1] / "data" / "knowledge_base"

# 不参与清洗的仓库（工具/无内容）
SKIP_REPOS = {"mianshiya", "interview_radar", "campus2026", "awesome_agent_dev", "awesome_llm_interview"}

# 文件名特征排除（dianping_interview 的 README 是面试重点精华，豁免）
SKIP_FILENAME_RE = re.compile(
    r"(^|/)(license|contribut|changelog|authors|credits|index|toc|目录|导航|关于|acknowledg)"
    r"|\.(png|jpg|jpeg|gif|svg|webp|ico|pdf|zip)$",
    re.I,
)
README_EXEMPT_REPOS = {"dianping_interview"}
SKIP_LANG_RE = re.compile(r"(中文|English|日本語|español|français|português|한국어|فارسی|Русский)")

EXCLUDE_MARKERS = (
    "贡献指南", "参与者公约", "免责声明", "copyright", "all rights reserved",
    "欢迎加入", "成为贡献者", "加群", "微信公众号", "知识星球", "本文章节",
)

# 项目题特征（业务/实现类）vs 八股题特征（概念/原理类）
PROJECT_MARKERS = (
    "项目", "秒杀", "黑马点评", "苍穹外卖", "瑞吉", "谷粒", "商城", "外卖", "系统设计", "架构设计",
    "如何实现", "怎么实现", "设计一个", "实现一个", "项目经历", "你做的", "你负责", "上线", "压测",
    "qps", "部署", "重构", "优化了", "遇到过", "踩坑", "面试官问", "一面", "二面", "三面", "反问",
    "业务", "需求", "场景题", "项目亮点", "简历",
)
BAGU_MARKERS = (
    "什么是", "是什么", "原理", "区别", "为什么", "底层", "源码", "实现原理", "怎么保证",
    "如何保证", "讲一下", "谈谈", "说一下", "了解", "机制", "线程", "jvm", "mysql", "redis",
    "spring", "tcp", "http", "http", "索引", "事务", "锁", "gc", "hashmap", "concurrenthashmap",
)

FAKE_INTERVIEW = ("面试官", "一面", "二面", "三面", "hr面", "面经", "反问环节", "自我介绍")
TUTORIAL_MARKERS = ("教程", "入门", "快速上手", "学习路径", "实战项目", "hello world", "安装", "配置环境")


def html_to_text(raw: str) -> str:
    """HTML → 纯文本：去 script/style/标签，解实体，保留代码块可读性。"""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=re.S | re.I)
    t = re.sub(r"<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t)


def extract_era(fn: str, text: str) -> str | None:
    """时效标签：文件名年份为主（作者标注的时效），内容首段仅辅助。

    范围限定 2015-2026（2026 为当前年，超出视为误抓）。文件名多个年份取最新。
    """
    def years_from(s: str) -> set[int]:
        out = set()
        for m in re.findall(r"(20(?:1[5-9]|2[0-6]))", s):
            out.add(int(m))
        for m in re.findall(r"(?<!\d)(\d{2})届", s):
            y = 2000 + int(m)
            if 2015 <= y <= 2026:
                out.add(y)
        return out

    years = years_from(fn)
    if not years:
        years = years_from(text[:200])
    return str(max(years)) if years else None


def clean_text(text: str) -> str:
    """文本归一：去图片/链接/emoji/导航噪音，保留代码块。"""
    t = text
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)          # 图片
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)       # 链接保留文字
    t = re.sub(r"<[^>]+>", "", t)                        # HTML 标签
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", t)  # emoji
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def classify_type(text: str) -> str:
    """内容类型：facejing(面经) | question_bank(真题库) | knowledge(知识体系) | tutorial | junk"""
    low = text.lower()
    n_fake = sum(1 for m in FAKE_INTERVIEW if m in low)
    n_tutorial = sum(1 for m in TUTORIAL_MARKERS if m in low)
    has_qa = bool(re.search(r"(^|\n)\s*[#>*\- ]*(问|q|题目|题)\s*[:：]?", text, re.M))
    if n_fake >= 2:
        return "facejing"
    if n_tutorial >= 3:
        return "tutorial"
    if has_qa or len(text) < 400:
        return "question_bank"
    return "knowledge"


def classify_bagu_project(text: str) -> str:
    """大分类：project | bagu。取特征分对比，平局归 bagu（八股兜底）。"""
    low = text.lower()
    p_score = sum(1 for m in PROJECT_MARKERS if m in low)
    b_score = sum(1 for m in BAGU_MARKERS if m in low)
    return "project" if p_score > b_score else "bagu"


def split_chunks(text: str, max_len: int = 2000) -> list[str]:
    """按二级标题/段落切块，保留标题上下文。"""
    parts = re.split(r"\n(?=#{1,3}\s)", text)
    chunks = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > max_len:
            # 长文档按段落再切
            segs = re.split(r"\n(?=\S)", p)
            cur = ""
            for seg in segs:
                if len(cur) + len(seg) > max_len and cur:
                    chunks.append(cur.strip())
                    cur = seg
                else:
                    cur += "\n" + seg
            if cur.strip():
                chunks.append(cur.strip())
        else:
            chunks.append(p)
    return chunks


def tag_scene(text: str) -> tuple[list[str], list[str]]:
    """项目场景标签：业务场景 + 技术特征（命中关键词即标）。"""
    with open(Path(__file__).resolve().parents[1] / "data" / "project_scenes.json", encoding="utf-8") as f:
        scenes = json.load(f)
    low = text.lower()
    biz, tech = [], []
    for s in scenes["business_scenes"]:
        if any(k in low for k in s["keywords"]):
            biz.append(s["name"])
    for s in scenes["tech_scenes"]:
        if any(k in low for k in s["keywords"]):
            tech.append(s["name"])
    return biz, tech


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stats = {
        "repos": {}, "type_counts": {}, "category_counts": {},
        "total_chunks": 0, "dropped_junk": 0, "dup_dropped": 0,
        "tag_coverage": {"company": 0, "roles": 0, "biz": 0, "tech": 0},
    }
    seen_hashes: set[str] = set()
    out_fp = OUT / "knowledge.jsonl"

    with open(out_fp, "w", encoding="utf-8") as out:
        for repo in sorted(os.listdir(SRC)):
            repo_dir = SRC / repo
            if not repo_dir.is_dir() or repo in SKIP_REPOS:
                continue
            repo_stats = {"files": 0, "chunks": 0}
            for dirpath, _dirnames, filenames in os.walk(repo_dir):
                if "/.git" in dirpath.replace("\\", "/"):
                    continue
                for fn in filenames:
                    is_md = fn.lower().endswith(".md")
                    is_html = fn.lower().endswith((".html", ".htm"))
                    # voice_interview_exp 的面经是无扩展名纯文本
                    is_plain = repo == "voice_interview_exp" and "." not in fn
                    is_readme = fn.lower() == "readme.md"
                    if (not is_md and not is_html and not is_plain) or (
                        SKIP_FILENAME_RE.search(fn)
                        and not (is_readme and repo in README_EXEMPT_REPOS)
                    ):
                        continue
                    fp = Path(dirpath) / fn
                    try:
                        raw = fp.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    if is_html:
                        raw = html_to_text(raw)
                    if len(raw) < 100 or any(m in raw for m in EXCLUDE_MARKERS):
                        stats["dropped_junk"] += 1
                        continue
                    text = clean_text(raw)
                    if len(text) < 100:
                        stats["dropped_junk"] += 1
                        continue
                    ctype = classify_type(text)
                    stats["type_counts"][ctype] = stats["type_counts"].get(ctype, 0) + 1
                    if ctype == "tutorial":
                        continue

                    category = classify_bagu_project(text)
                    stats["category_counts"][category] = stats["category_counts"].get(category, 0) + 1

                    era = extract_era(fn, text)

                    company = infer_company(f"{fn} {text[:500]}")
                    roles = infer_roles({"text": text[:3000]})
                    biz, tech = ([], [])
                    if category == "project":
                        biz, tech = tag_scene(text[:3000])

                    for i, chunk in enumerate(split_chunks(text)):
                        if len(chunk) < 80:
                            continue
                        key = hashlib.md5(re.sub(r"\s+", "", chunk).encode("utf-8")).hexdigest()
                        if key in seen_hashes:
                            stats["dup_dropped"] += 1
                            continue
                        seen_hashes.add(key)
                        entry = {
                            "id": f"{repo}_{repo_stats['files']}_{i}",
                            "source_repo": repo,
                            "source_file": str(fp.relative_to(SRC)).replace("\\", "/"),
                            "category": category,
                            "type": ctype,
                            "era": era,
                            "company": company,
                            "roles": roles,
                            "business_scene": biz,
                            "tech_scene": tech,
                            "title": fn[:60],
                            "content": chunk,
                        }
                        out.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        stats["total_chunks"] += 1
                        repo_stats["chunks"] += 1
                        if company:
                            stats["tag_coverage"]["company"] += 1
                        if roles:
                            stats["tag_coverage"]["roles"] += 1
                        if biz:
                            stats["tag_coverage"]["biz"] += 1
                        if tech:
                            stats["tag_coverage"]["tech"] += 1
            repo_stats["files"] = sum(1 for _ in (repo_dir.rglob("*.md")))
            stats["repos"][repo] = repo_stats

    # 报告
    meta = {
        "generated_at": "2026-08-14",
        "total_chunks": stats["total_chunks"],
        "dropped_junk": stats["dropped_junk"],
        "dup_dropped": stats["dup_dropped"],
        "type_counts": stats["type_counts"],
        "category_counts": stats["category_counts"],
        "tag_coverage": stats["tag_coverage"],
        "repos": stats["repos"],
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
