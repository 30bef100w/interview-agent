"""空答门禁、去重、评分消毒：纯函数，不碰 LLM。"""
import re

from .constants import (
    NON_ANSWER_MAX_SCORE,
    SKIP_EXACT,
    _DEDUP_KEY_GROUPS,
    _INJECTION_MARKERS,
    _RUBRIC_BAND_RE,
)

def looks_like_rubric(text: str | None) -> bool:
    """评分档位/空壳提纲，不能当候选人可见的参考答案。"""
    t = (text or "").strip()
    if not t:
        return False
    if len(_RUBRIC_BAND_RE.findall(t)) >= 2:
        return True
    if t.startswith("应包含") and len(t) < 160:
        return True
    if re.fullmatch(r"应(?:该)?(?:包含|讲清|说明).{0,100}", t):
        return True
    return False

def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _project_quotas(total: int, n_projects: int) -> list[int]:
    """项目题在多个简历项目间均分配额（相关度高的项目可多 1 题）。"""
    if total <= 0 or n_projects <= 0:
        return []
    base, rem = divmod(total, n_projects)
    return [base + (1 if i < rem else 0) for i in range(n_projects)]


def _question_mentions_project(topic: str, text: str, project_name: str) -> bool:
    """题签是否点名了某简历项目。"""
    if not project_name:
        return False
    blob = f"{topic or ''} {text or ''}"
    if project_name in blob:
        return True
    # 中文项目名片段（≥3 字）
    name = project_name.strip()
    if len(name) >= 3:
        for n in range(min(len(name), 12), 2, -1):
            for i in range(len(name) - n + 1):
                frag = name[i : i + n]
                if frag in blob:
                    return True
    return False


def _is_suspect_pure_backend_project_blob(blob: str, target_role: str) -> bool:
    """规则仅标记「疑似纯后端题签」，最终是否保留交给 LLM 诊断。"""
    if not target_role:
        return False
    from app.services.job_roles import agent_signal_count, resolve_target_roles

    roles = resolve_target_roles(target_role)
    if not roles or roles[0] not in {"agent_dev", "llm"}:
        return False
    low = (blob or "").lower()
    if agent_signal_count(low) >= 1:
        return False
    bridge = (
        "会话",
        "记忆",
        "上下文",
        "多轮",
        "token",
        "推理",
        "提示词",
        "工具",
        "编排",
        "评测",
        "agent",
    )
    if any(k in low for k in bridge):
        return False
    backend_kw = (
        "redis",
        "缓存击穿",
        "缓存穿透",
        "分布式锁",
        "kafka",
        "rocketmq",
        "jvm",
        "spring",
        "mybatis",
        "秒杀",
        "canal",
        "bloom",
        "布隆",
    )
    backend_hits = sum(1 for k in backend_kw if k in low)
    return backend_hits >= 2


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())

def _topic_key_tags(text: str) -> set[str]:
    t = (text or "").lower()
    tags: set[str] = set()
    for i, group in enumerate(_DEDUP_KEY_GROUPS):
        if any(k.lower() in t for k in group):
            tags.add(f"g{i}")
    return tags


def _conflicts_avoid(candidate: str, avoid_topics: list) -> bool:
    """考点角度冲突：同关键词组命中，或长子串包含。"""
    c_tags = _topic_key_tags(candidate)
    cn = _norm_text(candidate).lower()
    for raw in avoid_topics or []:
        a = str(raw or "")
        if a.startswith("coding:"):
            continue
        an = _norm_text(a).lower()
        if len(an) >= 6 and (an in cn or cn in an):
            return True
        a_tags = _topic_key_tags(a)
        if c_tags and a_tags and (c_tags & a_tags):
            return True
    return False


def _char_overlap_ratio(a: str, b: str) -> float:
    """粗粒度字符重合率，用于追问换句重复检测。"""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    return inter / max(len(sa), len(sb))


def _shared_project_hook(a: str, b: str) -> bool:
    """两题是否点到同一项目专名（如 MindBridge）。"""
    names_a = set(re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", a))
    names_b = set(re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", b))
    if names_a & names_b:
        return True
    for n in range(min(len(a), len(b), 10), 2, -1):
        for i in range(len(a) - n + 1):
            frag = a[i : i + n]
            if not re.search(r"[\u4e00-\u9fff]{3,}", frag):
                continue
            if frag not in b:
                continue
            if frag in ("怎么样", "如何实现", "请详细", "结合原理", "工程实践", "具体实现"):
                continue
            return True
    return False


def _is_similar_question(a: str, b: str) -> bool:
    """问法相似：同题/改写题。允许同知识点换角度，只挡换句重复。"""
    an = _norm_text(a).lower()
    bn = _norm_text(b).lower()
    if not an or not bn:
        return False
    if an == bn:
        return True
    if len(an) >= 10 and len(bn) >= 10 and (an in bn or bn in an):
        return True
    if len(an) >= 12 and len(bn) >= 12:
        len_ratio = min(len(an), len(bn)) / max(len(an), len(bn))
        if len_ratio >= 0.55 and _char_overlap_ratio(an, bn) >= 0.72:
            return True
    # 同项目专名 + 同技术簇 + 措辞较接近 → 换句重复（不是「MCP 永远不问」）
    if _shared_project_hook(an, bn) and (_topic_key_tags(a) & _topic_key_tags(b)):
        if _char_overlap_ratio(an, bn) >= 0.42:
            return True
    return False


def _conflicts_historical_question(candidate: str, avoid_topics: list) -> bool:
    """跨场历史去重：只挡与历史问法高度相似的换句重复。

    不按词表永久封杀考点——这场问过 MCP，以后仍可换角度再问。
    空泛「如何编排」对历史同类空泛题额外拦截。
    """
    cand_vague = _looks_like_vague_orchestration(candidate)
    for raw in avoid_topics or []:
        a = str(raw or "")
        if a.startswith("coding:"):
            continue
        if _is_similar_question(candidate, a):
            return True
        if cand_vague and _looks_like_vague_orchestration(a):
            return True
    return False


def _conflicts_bagu_knowledge(candidate: str, occupied: list) -> bool:
    """八股去重：挡题库同一条目 / 换句复述，不按知识点簇整类封杀。

    LangChain 与 LangGraph 换角度可以都问；同一条原题改写则不行。
    """
    blob = str(candidate or "").strip()
    if len(blob) < 6:
        return False
    for raw in occupied or []:
        a = str(raw or "").strip()
        if a.startswith("coding:") or len(a) < 6:
            continue
        if _is_similar_question(blob, a):
            return True
    return False


def _conflicts_plan_sibling(candidate: str, siblings: list) -> bool:
    """同场题签互斥：只挡几乎同一题干/换句重复，不用词表把整场 Agent 题砍光。"""
    cn = _norm_text(candidate).lower()
    if len(cn) < 6:
        return False
    for raw in siblings or []:
        an = _norm_text(str(raw or "")).lower()
        if an.startswith("coding:") or len(an) < 6:
            continue
        if _is_similar_question(candidate, str(raw)):
            return True
    return False


def _looks_like_vague_orchestration(text: str) -> bool:
    """空泛「如何编排/设计多 Agent」类题——跨场/出题时重点打压。"""
    t = (text or "").lower()
    if not t:
        return False
    vague = (
        "如何编排",
        "怎么编排",
        "多智能体编排",
        "多agent编排",
        "如何设计多",
        "怎么设计多",
        "怎么设计一个agent",
        "如何设计一个agent",
        "编排流程",
        "agent编排",
    )
    if any(v in t for v in vague):
        # 若同时没有失败/指标/权限等落地词，视为空泛
        concrete = ("失败", "重试", "降级", "超时", "评测", "指标", "权限", "幻觉", "trace", "幂等")
        return not any(c in t for c in concrete)
    return False


def _is_repeat_followup(follow_q: str, prior_questions: list[str], answers: list[str]) -> bool:
    """追问是否与本题已问问题/已答考点重复（硬拦截）。"""
    fq = (follow_q or "").strip()
    if not fq:
        return True
    # 1) 与已问问题撞考点 / 高重合
    if _conflicts_avoid(fq, prior_questions):
        return True
    fn = _norm_text(fq).lower()
    for prev in prior_questions:
        pn = _norm_text(prev).lower()
        if not pn:
            continue
        if fn == pn:
            return True
        if len(fn) >= 8 and len(pn) >= 8 and (fn in pn or pn in fn):
            return True
        if len(fn) >= 10 and len(pn) >= 10 and _char_overlap_ratio(fn, pn) >= 0.72:
            return True
    # 2) 追问考点已被候选人作答覆盖（如已讲清穿透，又问穿透）
    ans_blob = " ".join(str(a) for a in (answers or []) if a)
    fq_tags = _topic_key_tags(fq)
    ans_tags = _topic_key_tags(ans_blob)
    if fq_tags and ans_tags and fq_tags <= ans_tags:
        return True
    return False


# 提示词注入 / 元指令：不是对本题的实质作答
_INJECTION_MARKERS = (
    "提示词",
    "忽视之前",
    "忽略之前",
    "忽略以上",
    "忽视以上",
    "并非是回答",
    "不是回答",
    "不是在回答",
    "新的提示",
    "下一轮问题打出",
    "ignore previous",
    "ignore all previous",
    "system prompt",
)


def _is_failed_coding_submit(text: str) -> bool:
    t = (text or "").strip()
    if not (t.startswith("[代码提交]") or t.startswith("[算法题作答]")):
        return False
    low = t.lower()
    return any(
        k in low
        for k in (
            "wrong_answer",
            "runtime_error",
            "time_limit",
            "compile_error",
            "memory_limit",
            "判定：错误",
            "判定:错误",
        )
    )


def _is_thin_answer(text: str) -> bool:
    """跳过/敷衍/过短/注入：不能据此写技术亮点。"""
    t = (text or "").strip().rstrip("。.!！?？~…")
    if not t:
        return True
    # 判题失败视作未有效作答；通过的代码提交留给 AI 评审分
    if _is_failed_coding_submit(t):
        return True
    if t.startswith("[代码提交]") or t.startswith("[算法题作答]"):
        return False
    if t.lower() in SKIP_EXACT or t in SKIP_EXACT:
        return True
    if len(t) <= 10 and any(k in t for k in ("下一个", "下一题", "跳过", "不会", "不知道", "没思路")):
        return True
    # 极短无信息（如「嗯」「好」）；注意不要误伤「回答内容」这类占位句
    if len(_norm_text(t)) <= 2:
        return True
    # 提示词注入 / 要求模型改行为：一律按未有效作答硬封顶
    low = t.lower()
    if any(m.lower() in low for m in _INJECTION_MARKERS):
        return True
    return False


def is_non_answer(answers: list[str] | None) -> bool:
    texts = [str(a).strip() for a in (answers or []) if str(a).strip()]
    if not texts:
        return True
    return all(_is_thin_answer(a) for a in texts)


def _has_ngram_overlap(strength: str, answers: list[str], n: int = 2) -> bool:
    """strength 是否包含候选人作答中的连续片段（防止题干/简历幻觉亮点）。"""
    s = _norm_text(strength)
    if not s:
        return False
    for a in answers:
        a_n = _norm_text(str(a))
        if len(a_n) < n:
            continue
        for size in range(min(6, len(a_n)), n - 1, -1):
            for i in range(0, len(a_n) - size + 1):
                if a_n[i : i + size] in s:
                    return True
    return False


def filter_strengths(strengths: list | None, answers: list[str] | None, score: float | None = None) -> list[str]:
    raw = [str(x).strip() for x in (strengths or []) if str(x).strip() and str(x).strip() != "无"]
    if is_non_answer(answers):
        return []
    answers = [str(a) for a in (answers or []) if str(a).strip()]
    grounded = [s for s in raw if _has_ngram_overlap(s, answers, 2)]
    if grounded:
        return grounded
    joined_len = sum(len(_norm_text(a)) for a in answers)
    # 作答足够长且分数不低时，保留 LLM 优点（仍已排除空答幻觉）
    if joined_len >= 40 and float(score or 0) >= 6:
        return raw
    return []


def sanitize_score_fields(
    answers: list[str] | None,
    score: object,
    strengths: list | None,
    weaknesses: list | None,
) -> tuple[float, list[str], list[str]]:
    """引擎硬校验：空答/跳过封顶，并清掉无作答依据的 strengths。"""
    try:
        sc = float(score)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        sc = 5.0
    sc = max(1.0, min(10.0, sc))
    weak = [str(x).strip() for x in (weaknesses or []) if str(x).strip()]
    if is_non_answer(answers):
        sc = min(sc, NON_ANSWER_MAX_SCORE)
        if not weak:
            weak = ["未有效回答本题要点"]
        return sc, [], weak
    strengths_f = filter_strengths(strengths, answers, sc)
    return sc, strengths_f, weak
