"""面试状态机引擎：LLM 只生成语言，控制决策归引擎。

无状态服务模式：引擎方法都是 (state, input) -> (new_state, output) 纯推进，
DB 持久化由 API 层负责。llm 通过构造注入（LlmPort），单测传 fake，不依赖 FastAPI。
"""
import json
import logging
import re
import time

from app.prompts.interview import (
    ASK_QUESTION_SYSTEM,
    BAGU_SELECT_SYSTEM,
    FINAL_REPORT_SYSTEM,
    FOLLOW_UP_SYSTEM,
    INTERVIEWER_SYSTEM,
    OPENING_SYSTEM,
    PLANNER_SYSTEM,
    ROUTER_SYSTEM,
    SCORE_SYSTEM,
)
from app.schemas.interview import InterviewState, PerQuestion
from app.services.llm.client import LlmPort
from app.services.question_bank import pick_coding_question

logger = logging.getLogger(__name__)

MAX_FOLLOW_UPS_PER_QUESTION = 2  # 防同题反复纠缠；宁可换下一题
# 随用户选定轮次放宽上限（选 11 轮就应能排到约 11 题，不再死卡 5）
PROJECT_CLAMP = (0, 10)
BA_GU_CLAMP = (1, 10)
ANSWER_TRUNCATE = 500
NON_ANSWER_MAX_SCORE = 1.0
ASK_BACK_TEXT = "我的问题问完了。你有什么想反问我的吗？"
SUMMARIZING_TEXT = "本轮面试已全部结束，正在汇总你的表现并生成报告，请稍候…"

# 项目题补齐用的差异化角度（防全场都在「如何编排」）
_DIVERSE_PROJECT_ANGLES: tuple[tuple[str, str], ...] = (
    ("工具失败与降级", "工具/MCP 调用失败、超时、重试、降级与幂等，禁止空泛谈编排"),
    ("RAG 质量与评测", "检索召回、重排、幻觉控制与效果评测指标"),
    ("记忆与上下文", "短长期记忆、上下文窗口、会话隔离与过期策略"),
    ("权限与安全", "工具权限、数据隔离、提示注入与越权防护"),
    ("可观测性", "trace/日志、关键指标、线上如何定位一次失败调用"),
    ("多角色协作边界", "分工、handoff 失败、状态一致性——必须落到具体失败场景"),
    ("评测与线上效果", "离线指标、人工抽检、badcase 回流与回归"),
    ("成本与延迟", "一次请求的 token/耗时构成，怎么降本不伤效果"),
    ("数据与隐私", "训练/日志数据脱敏、留存、越权访问怎么防"),
    ("灰度与回滚", "Agent 能力上线如何灰度，出问题怎么快速回滚"),
)
WEAK_KEYWORDS = ("不会", "不知道", "没做过", "没学过", "不了解", "没思路", "答不上来", "没接触过", "忘了")
SKIP_EXACT = {
    "下一个",
    "下一题",
    "跳过",
    "过",
    "不会",
    "不知道",
    "没做过",
    "不清楚",
    "无",
    "没有",
    "pass",
    "skip",
    "next",
}


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


# 去重用的高频考点关键词（命中同一组即视为重复角度）
_DEDUP_KEY_GROUPS: tuple[tuple[str, ...], ...] = (
    ("缓存穿透", "穿透", "bloom", "布隆"),
    ("缓存击穿", "击穿", "热点key", "互斥锁重建"),
    ("缓存雪崩", "雪崩", "随机ttl", "过期雪崩"),
    ("缓存一致性", "双写", "canal", "最终一致"),
    ("分布式锁", "redis锁", "红锁", "lua脚本"),
    ("限流", "令牌桶", "漏桶", "熔断"),
    ("消息队列", "kafka", "rocketmq", "投递语义", "幂等消费"),
    ("索引", "b+树", "慢查询", "覆盖索引"),
    ("事务", "隔离级别", "mvcc", "幻读"),
    ("接雨水", "trapping rain", "rain water"),
    # Agent / LLM 应用（防每场都问同一项目的 MCP/RAG）
    ("mcp", "工具调用", "function calling", "tool calling", "外部工具", "tool use"),
    ("rag", "检索增强", "向量检索", "embedding", "召回重排"),
    ("多智能体", "multi-agent", "多agent", "agent协作", "handoff", "supervisor"),
    ("任务规划", "plan-and-execute", "planning agent", "agent规划", "编排", "如何编排", "工作流编排"),
    ("记忆管理", "短期记忆", "长期记忆", "memory", "上下文管理"),
    ("prompt", "提示词", "prompt工程", "提示工程"),
)

# TODO(vNext): 可选「知识点簇屏蔽」——按 LangChain/RAG/MCP 等簇限制本场八股密度。
# 当前只去题库同一条目/换句重复，不整类封杀考点。


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


class InterviewEngine:
    def __init__(self, llm: LlmPort) -> None:
        self.llm = llm
        self._enterprise_hits: list[dict] = []
        self._company_display: str = ""
        self._asked_norms: set[str] = set()
        self._plan_roles: list[str] = []
        self._plan_skills: list[str] = []
        self._plan_company_id: str | None = None
        self._plan_project_n = 0
        self._plan_ba_gu_n = 0
        self._plan_hr_n = 0
        self._plan_role_explicit = False
        self._proj_q_role_cache: dict[str, bool] = {}
        self._askable_capacity: dict = {}

    # ---------- 创建会话：开场白 + 路由 + 规划（题签）→ 面试计划就绪 ----------

    def create(
        self,
        session_id: int,
        resume_raw: str,
        profile: dict,
        total_rounds: int,
        mode: str,
        interview_type: str,
        target_role: str = "",
        target_company: str = "",
        practice_focus: str = "",
        skip_coding: bool = False,
        review_mode: bool = False,
        avoid_topics: list[str] | None = None,
        asked_norms: set[str] | None = None,
    ):
        """创建会话并完成整场面试的规划（题签级），stage 停在 INTRO 等自我介绍。

        规划前置：路由（比例分配）+ 检索（面试规划师）+ 拷打链生成 + 规划（题单）都在这里完成，
        自我介绍回答后直接出第一题，不再等待规划。
        target_role/target_company：目标岗位/企业（JD 定向）——target_role 统领全局。
        asked_norms：近期同岗位问过的题目（归一化），召回时降权去重。
        """
        state = InterviewState(
            session_id=session_id,
            resume_raw=resume_raw,
            profile=profile,
            total_rounds=total_rounds,
            target_role=target_role.strip(),
            target_company=target_company.strip(),
            practice_focus=practice_focus.strip()[:500],
            skip_coding=bool(skip_coding),
            review_mode=bool(review_mode),
            avoid_topics=list(avoid_topics or [])[:80],
        )
        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        from app.services.create_timing_log import step as trace_step

        t_open = time.perf_counter()
        opening = self.llm.chat_text(OPENING_SYSTEM, self._ctx_block(state))
        timings["opening_llm_s"] = time.perf_counter() - t_open
        trace_step(session_id, "opening_llm", duration_s=round(timings["opening_llm_s"], 2))
        state.history.append({"role": "interviewer", "text": opening})

        # 1) 召回 + 拷打链（与题单分开生成，互不替代）
        t_ret = time.perf_counter()
        self._plan_retrieval(state, asked_norms or set(), timings)
        timings["plan_retrieval_s"] = time.perf_counter() - t_ret
        trace_step(
            session_id,
            "plan_retrieval",
            duration_s=round(timings["plan_retrieval_s"], 2),
            role_hits=int(timings.get("retrieval_role_hits_n") or 0),
            scene_hits=int(timings.get("retrieval_scene_hits_n") or 0),
            chains=int(timings.get("project_chains_n") or 0),
        )

        # 2) Router 定项目/八股比例
        t_router = time.perf_counter()
        project_n, ba_gu_n, hr_n = self._plan_counts(state, mode, interview_type)
        timings["router_s"] = time.perf_counter() - t_router
        trace_step(
            session_id,
            "router",
            duration_s=round(timings["router_s"], 2),
            project_n=project_n,
            ba_gu_n=ba_gu_n,
            hr_n=hr_n,
        )

        # 3) 规划官出题单（项目主问 + HR；拷打链仅用于后续追问）
        t_plan = time.perf_counter()
        self._build_plan(state, mode, project_n, ba_gu_n, hr_n)
        timings["build_plan_s"] = time.perf_counter() - t_plan
        trace_step(session_id, "build_plan", duration_s=round(timings["build_plan_s"], 2))

        self._annotate_original_company(state)
        timings["create_total_s"] = time.perf_counter() - t0
        state.create_timings = {k: round(v, 2) for k, v in timings.items()}
        trace_step(session_id, "engine_done", timings=state.create_timings)
        chain_projects = [str(c.get("project") or "") for c in (state.project_chains or [])]
        plan_proj_topics = [
            str(q.get("topic") or "")[:40]
            for q in (state.plan or [])
            if q.get("type") == "project"
        ]
        logger.info(
            "interview_create_timing session=%s role=%s mode=%s "
            "project_n=%d ba_gu_n=%d hr_n=%d chains=%s plan_projects=%s timings=%s",
            session_id,
            target_role or "(none)",
            mode,
            project_n,
            ba_gu_n,
            hr_n,
            chain_projects,
            plan_proj_topics,
            {k: round(v, 2) for k, v in timings.items()},
        )
        return state, opening

    def _plan_retrieval(
        self,
        state: InterviewState,
        asked_norms: set[str],
        timings: dict[str, float] | None = None,
    ) -> None:
        from app.observability.node_trace import trace_node

        with trace_node("plan_retrieval", session_id=state.session_id):
            self._plan_retrieval_impl(state, asked_norms, timings)

    def _plan_retrieval_impl(
        self,
        state: InterviewState,
        asked_norms: set[str],
        timings: dict[str, float] | None = None,
    ) -> None:
        """多路召回（存 retrieved_material）+ 生成项目拷打链（存 project_chains）。

        A 路：目标岗位真题（岗位硬过滤 + LLM 复核）
        B 路：简历项目场景真题（同样硬卡岗位 + LLM 复核）
        拷打链：每简历项目独立生成，供面试追问；不写入题单主问。
        """
        from app.services import knowledge_retrieval as kr
        from app.services import project_cross as pc
        from app.services.job_roles import (
            company_display_name,
            infer_roles,
            resolve_company_id,
            resolve_target_roles,
        )

        profile = state.profile or {}
        if state.target_role:
            roles = resolve_target_roles(state.target_role)
        else:
            roles = infer_roles(profile)[:3]

        company_id = resolve_company_id(state.target_company) if state.target_company else None
        company_label = (
            company_display_name(company_id or state.target_company)
            if (company_id or state.target_company)
            else ""
        )

        skills = [str(s) for s in (profile.get("skills") or [])]
        scenes: list[str] = []
        seen_sc: set[str] = set()
        for p in profile.get("projects") or []:
            for x in p.get("scene_tags") or []:
                s = str(x).strip()
                if s and s not in seen_sc:
                    seen_sc.add(s)
                    scenes.append(s)
        retrieve_skills = skills[:6] if roles else skills
        _t = time.perf_counter

        # —— A 路：岗位（有企业时：企业原题 + 无企业标签 双路合并）——
        role_hits: list[dict] = []
        if roles:
            if company_id:
                company_role = kr.retrieve(
                    roles=roles,
                    company=company_id,
                    skills=retrieve_skills,
                    scenes=None,
                    asked_norms=asked_norms,
                    top_n=8,
                    min_score=20,
                )
                untagged_role = kr.retrieve(
                    roles=roles,
                    company=None,
                    skills=retrieve_skills,
                    scenes=None,
                    asked_norms=asked_norms,
                    top_n=8,
                    min_score=20,
                )
                role_hits = kr.merge_company_and_untagged(
                    company_role,
                    untagged_role,
                    company=company_id,
                    limit=12,
                )
            else:
                role_hits = kr.retrieve(
                    roles=roles,
                    company=None,
                    skills=retrieve_skills,
                    scenes=None,  # 场景走 B 路，避免和岗位硬门槛搅在一起
                    asked_norms=asked_norms,
                    top_n=10,
                    min_score=20,
                )
            if len(role_hits) < 6:
                more_plain = kr.search_questions(
                    roles=roles,
                    company=None,
                    asked_norms=asked_norms,
                    top_n=12,
                    min_score=10,
                )
                if company_id:
                    more_co = kr.search_questions(
                        roles=roles,
                        company=company_id,
                        asked_norms=asked_norms,
                        top_n=12,
                        min_score=10,
                    )
                    role_hits = kr.merge_company_and_untagged(
                        more_co,
                        more_plain,
                        company=company_id,
                        limit=12,
                        extra=role_hits,
                    )
                else:
                    role_hits = kr.merge_hits(role_hits, more_plain, limit=12)
            role_hits = kr.sanitize_hits(
                role_hits, roles=roles, company=company_id, require_role=True
            )
            t_llm = _t()
            role_hits = self._filter_hits_by_llm(
                roles, role_hits, session_id=state.session_id, lane="role_filter"
            )
            if timings is not None:
                timings["retrieval_role_llm_filter_s"] = _t() - t_llm
            from app.services.create_timing_log import step as trace_step

            trace_step(
                state.session_id,
                "retrieval_role_filter",
                duration_s=round(timings.get("retrieval_role_llm_filter_s", 0), 2)
                if timings
                else 0,
                hits=len(role_hits),
            )
        else:
            # 无岗位：技能/场景合一召回，仍分区时场景路会再补一轮
            role_hits = kr.retrieve(
                roles=None,
                company=company_id,
                skills=retrieve_skills,
                scenes=scenes,
                asked_norms=asked_norms,
                top_n=10,
                min_score=30,
            )

        scene_roles = roles if roles else None
        # —— B 路：项目场景（有岗位时同样硬卡岗位标签）——
        scene_hits: list[dict] = []
        if scenes:
            if company_id:
                company_scene = kr.retrieve(
                    roles=scene_roles,
                    company=company_id,
                    skills=None,
                    scenes=scenes,
                    category="project",
                    asked_norms=asked_norms,
                    top_n=6,
                    min_score=20,
                )
                untagged_scene = kr.retrieve(
                    roles=scene_roles,
                    company=None,
                    skills=None,
                    scenes=scenes,
                    category="project",
                    asked_norms=asked_norms,
                    top_n=8,
                    min_score=25,
                )
                scene_hits = kr.merge_company_and_untagged(
                    company_scene,
                    untagged_scene,
                    company=company_id,
                    limit=10,
                )
            else:
                scene_hits = kr.retrieve(
                    roles=scene_roles,
                    company=None,
                    skills=None,
                    scenes=scenes,
                    category="project",
                    asked_norms=asked_norms,
                    top_n=8,
                    min_score=25,
                )
            if len(scene_hits) < 4:
                more = kr.search_questions(
                    roles=scene_roles,
                    skills=retrieve_skills[:4] or None,
                    scenes=scenes,
                    category="project",
                    asked_norms=asked_norms,
                    top_n=8,
                    min_score=15,
                )
                if company_id:
                    more_co = kr.search_questions(
                        roles=scene_roles,
                        company=company_id,
                        scenes=scenes,
                        category="project",
                        asked_norms=asked_norms,
                        top_n=6,
                        min_score=10,
                    )
                    scene_hits = kr.merge_company_and_untagged(
                        more_co,
                        more,
                        company=company_id,
                        limit=10,
                        extra=scene_hits,
                    )
                else:
                    scene_hits = kr.merge_hits(scene_hits, more, limit=10)
            # 再补一轮不限 category，防止场景项目题过少
            if len(scene_hits) < 4:
                more2 = kr.search_questions(
                    roles=scene_roles,
                    scenes=scenes,
                    asked_norms=asked_norms,
                    top_n=8,
                    min_score=20,
                )
                scene_hits = kr.merge_hits(scene_hits, more2, limit=10)
            scene_hits = kr.sanitize_hits(
                scene_hits,
                roles=roles,
                company=company_id,
                require_role=bool(roles),
            )
        if roles and scene_hits:
            t_llm = _t()
            scene_hits = self._filter_hits_by_llm(
                roles, scene_hits, session_id=state.session_id, lane="scene_filter"
            )
            if timings is not None:
                timings["retrieval_scene_llm_filter_s"] = _t() - t_llm
            from app.services.create_timing_log import step as trace_step

            trace_step(
                state.session_id,
                "retrieval_scene_filter",
                duration_s=round(timings.get("retrieval_scene_llm_filter_s", 0), 2)
                if timings
                else 0,
                hits=len(scene_hits),
            )

        if timings is not None:
            timings["retrieval_role_hits_n"] = float(len(role_hits))
            timings["retrieval_scene_hits_n"] = float(len(scene_hits))

        # 供规划后回填「企业原题」徽标（前端展示名）——岗位路 + 场景路里的企业题
        self._enterprise_hits = [
            h
            for h in (role_hits + scene_hits)
            if company_id and h.get("company") == company_id
        ]
        self._company_display = company_label
        self._asked_norms = asked_norms
        self._plan_roles = list(roles or [])
        self._plan_skills = list(retrieve_skills or [])
        self._plan_company_id = company_id
        self._plan_role_explicit = bool(state.target_role.strip())

        state.retrieved_material = kr.format_dual_hits(
            role_hits,
            scene_hits,
            company=company_id,
            company_label=company_label,
            role_limit=8,
            scene_limit=8,
        )

        # 拷打链：与题单分开；每简历项目各生成一条完整链（失败跳过单项目）
        t_chains = _t()
        state.project_chains = pc.build_project_chains(
            self.llm,
            profile,
            state.target_role,
            role_ids=roles,
            asked_norms=asked_norms,
            company=company_id,
            session_id=state.session_id,
        )
        if timings is not None:
            timings["project_chains_s"] = _t() - t_chains
            timings["project_chains_n"] = float(len(state.project_chains or []))
        from app.services.create_timing_log import step as trace_step

        trace_step(
            state.session_id,
            "project_chains",
            duration_s=round(timings.get("project_chains_s", 0), 2) if timings else 0,
            chains=len(state.project_chains or []),
        )

    def _filter_hits_by_llm(
        self,
        roles: list[str],
        hits: list[dict],
        session_id: int | None = None,
        *,
        lane: str = "role_filter",
    ) -> list[dict]:
        """LLM 语义校验：按题目内容剔除与目标岗位无关的题（防规则标签误标）。

        被剔除的题写入 tag_mismatch 审核队列，供运维定期处理。
        失败降级：返回原 hits（不阻塞面试）。
        """
        from app.services.session_guard_log import log_guard

        if not hits:
            return hits
        from app.services.job_roles import role_name

        role_label = "、".join(role_name(r) for r in roles[:2])
        lines = [f"{i + 1}. {h.get('question','')}" for i, h in enumerate(hits)]
        agent_extra = ""
        if roles and roles[0] in {"agent_dev", "llm"}:
            agent_extra = (
                "\n特别规则：目标岗位是 AI Agent / 大模型应用时，"
                "必须剔除纯 Java 后端、纯 Redis 缓存、MQ、JVM、分布式锁、秒杀等串岗题；"
                "只保留 Agent/RAG/工具调用/记忆/编排/评测/多智能体相关，"
                "或能把业务项目改写成 Agent 视角的题。"
            )
        user = (
            f"目标岗位：{role_label}\n"
            "以下是检索出的候选面试题（编号+题目），剔除与目标岗位无关的题：\n"
            "必须剔除：目录/合集标题、求职攻略、错题乱题、明显文不对题、"
            "与目标岗位无关的串岗题、纯复制粘贴无技术含量的碎片。\n"
            "如目标岗位是 Java 后端，C/C++ 题、前端题、算法岗题、运维题等都要剔除；"
            "与岗位相关但更偏其他细分方向的题（如 Java 岗中的前端题）也要剔除。"
            + agent_extra
            + "\n\n"
            + "\n".join(lines)
            + "\n\n只输出保留的题号数组，如 {\"keep\": [1, 3, 5]}，不要任何其他文字。"
        )
        try:
            result = self.llm.chat_json(
                "你是岗位匹配专家，严格按目标岗位筛选面试题。输出 JSON，不要任何其他文字。",
                user,
                max_retries=1,
            )
            keep = [int(x) for x in (result.get("keep") or [])]
            keep_set = {i for i in keep if 1 <= i <= len(hits)}
            kept = [hits[i - 1] for i in sorted(keep_set)]
            removed = [h for i, h in enumerate(hits, start=1) if i not in keep_set]
            if removed:
                from app.services.tag_mismatch_queue import enqueue_llm_filtered_hits

                enqueue_llm_filtered_hits(
                    removed,
                    roles=roles,
                    lane=lane,
                    session_id=session_id,
                )
            # 过滤后若为空（LLM 判断全无关），保留原样由规划官兜底
            if not kept:
                log_guard(
                    session_id,
                    "llm_filter_empty_kept_original",
                    lane=lane,
                    before_n=len(hits),
                )
            return kept if kept else hits
        except Exception as exc:  # noqa: BLE001
            log_guard(
                session_id,
                "llm_filter_degraded",
                lane=lane,
                before_n=len(hits),
                reason=type(exc).__name__,
            )
            return hits

    def _project_question_role_ok(self, blob: str, target_role: str) -> bool:
        """项目题签岗位适配：规则只标疑似，歧义题交 LLM 诊断（避免误杀 Redis-in-Agent 等）。"""
        if not target_role or not (blob or "").strip():
            return True
        cache_key = f"{target_role}::{blob[:240]}"
        if cache_key in self._proj_q_role_cache:
            return self._proj_q_role_cache[cache_key]
        if not _is_suspect_pure_backend_project_blob(blob, target_role):
            self._proj_q_role_cache[cache_key] = True
            return True
        if self.llm is None:
            self._proj_q_role_cache[cache_key] = False
            return False
        user = (
            f"目标岗位：{target_role}\n"
            f"项目题签：{blob[:500]}\n\n"
            "该题签是否适合目标岗位面试？\n"
            "- 保留：能从岗位视角深挖（例 Redis 用于 Agent 会话记忆/工具结果缓存/RAG 热数据）\n"
            "- 剔除：纯 Java 后端考点（缓存击穿、分布式锁、JVM）且无法合理改写成岗位题\n"
            '只输出 JSON：{"keep": true/false, "reason": "一句话"}'
        )
        try:
            result = self.llm.chat_json(
                "你是岗位匹配专家，判断项目面试题签是否适合目标岗位。",
                user,
                max_retries=1,
            )
            ok = bool(result.get("keep"))
        except Exception:  # noqa: BLE001
            ok = False
        self._proj_q_role_cache[cache_key] = ok
        return ok

    def _llm_diagnose_project_askable(
        self,
        project_name: str,
        project: dict,
        target_role: str,
        resume_raw: str,
    ) -> dict:
        """LLM 诊断：混合栈/边界项目是否值得从岗位视角深挖。"""
        user = (
            f"目标岗位：{target_role}\n"
            f"项目名：{project_name}\n"
            f"项目画像：{json.dumps(project, ensure_ascii=False)[:1200]}\n"
            f"简历摘录：{(resume_raw or '')[:800]}\n\n"
            "即使主技术栈是 Java/Redis，只要简历里写过 Agent/RAG/智能体相关工作，"
            "或可以用目标岗位视角合理深挖，就应判为可问。"
            'JSON: {"askable": true/false, "slots": 1-2, "angle": "建议问法方向"}'
        )
        try:
            return self.llm.chat_json(
                "你是岗位匹配专家，判断简历项目是否适合目标岗位面试深挖。",
                user,
                max_retries=1,
            )
        except Exception:  # noqa: BLE001
            return {"askable": False}

    def _refine_askable_capacity(self, state: InterviewState, capacity: dict) -> dict:
        """对规则未覆盖的边界项目做 LLM 诊断（如点评项目里含 Agent 段落）。"""
        from app.services.job_roles import (
            agent_signal_count,
            project_role_score,
            rank_resume_projects,
            resolve_target_roles,
        )

        if not state.target_role:
            return capacity
        profile = state.profile or {}
        role_ids = resolve_target_roles(state.target_role)
        askable = list(capacity.get("askable") or [])
        names = {str(x.get("name") or "") for x in askable}
        for p in rank_resume_projects(profile, state.target_role)[:3]:
            name = str(p.get("name") or "").strip()
            if not name or name in names:
                continue
            text = json.dumps(p, ensure_ascii=False)
            score = project_role_score(p, role_ids, profile)
            if score >= 0.5 or agent_signal_count(text) >= 1:
                continue
            if score < -0.5:
                continue
            diag = self._llm_diagnose_project_askable(
                name, p, state.target_role, state.resume_raw
            )
            if not diag.get("askable"):
                continue
            chain_n = 0
            for pc in state.project_chains or []:
                if str(pc.get("project") or "").strip() == name:
                    chain_n = len(pc.get("chains") or [])
                    break
            askable.append(
                {
                    "kind": "project",
                    "name": name,
                    "slots": min(2, max(1, int(diag.get("slots") or 1))),
                    "role_score": score,
                    "chain_count": chain_n,
                    "mixed_stack": True,
                    "llm_diagnosed": True,
                    "angle": str(diag.get("angle") or ""),
                }
            )
            names.add(name)
        capacity["askable"] = askable
        capacity["max_project_questions"] = sum(int(x.get("slots") or 0) for x in askable)
        capacity["has_askable"] = capacity["max_project_questions"] > 0
        capacity["role_relevant_items"] = len(askable)
        return capacity

    def _balance_project_plan(
        self,
        state: InterviewState,
        projects: list[dict],
        project_n: int,
    ) -> list[dict]:
        """岗位优先 + 多项目均衡：按相关度排序后轮转分配，抑制单项目霸场。"""
        from app.services.job_roles import resume_project_names

        if project_n <= 0:
            return []
        names = resume_project_names(state.profile or {}, state.target_role or "", limit=3)
        if not names:
            return projects[:project_n]

        quotas = _project_quotas(project_n, len(names))
        buckets: dict[str, list[dict]] = {n: [] for n in names}
        orphans: list[dict] = []
        for item in projects:
            if str(item.get("type") or "") != "project":
                orphans.append(item)
                continue
            blob = self._plan_blob(item)
            if not self._project_question_role_ok(blob, state.target_role or ""):
                continue
            matched = next(
                (
                    n
                    for n in names
                    if _question_mentions_project(
                        str(item.get("topic") or ""),
                        str(item.get("text") or ""),
                        n,
                    )
                ),
                None,
            )
            if matched:
                buckets[matched].append(item)
            else:
                orphans.append(item)

        def _make_slot(project_name: str, angle: tuple[str, str] | None = None) -> dict:
            topic, text = angle or _DIVERSE_PROJECT_ANGLES[0]
            return {
                "qid": "",
                "type": "project",
                "topic": f"{project_name} · {topic}"[:80],
                "text": f"结合项目「{project_name}」说明：{text}"[:220],
                "rubric": "6分:能说到点 8分:有方案与取舍 9分:有失败案例与指标",
                "original_company": "",
            }

        def _chain_items_for(project_name: str) -> list[dict]:
            out: list[dict] = []
            for pc in state.project_chains or []:
                if str(pc.get("project") or "").strip() != project_name:
                    continue
                for c in pc.get("chains") or []:
                    q = str(c.get("question") or "").strip()
                    intent = str(c.get("intent") or c.get("trigger") or "项目深挖").strip()
                    if not q:
                        continue
                    out.append(
                        {
                            "qid": "",
                            "type": "project",
                            "topic": f"{project_name}：{intent[:40]}"[:80],
                            "text": q[:220],
                            "rubric": "6分:能说到点 8分:有方案与取舍 9分:有失败案例与指标",
                            "original_company": "",
                        }
                    )
            return out

        result: list[dict] = []
        angle_idx = 0
        for name, quota in zip(names, quotas):
            pool = list(buckets.get(name) or [])
            chain_pool = _chain_items_for(name)
            taken = 0
            while taken < quota and len(result) < project_n:
                if pool:
                    result.append(pool.pop(0))
                    taken += 1
                    continue
                if chain_pool:
                    cand = chain_pool.pop(0)
                    if self._project_question_role_ok(
                        self._plan_blob(cand), state.target_role or ""
                    ):
                        result.append(cand)
                        taken += 1
                        continue
                angle = _DIVERSE_PROJECT_ANGLES[angle_idx % len(_DIVERSE_PROJECT_ANGLES)]
                angle_idx += 1
                result.append(_make_slot(name, angle))
                taken += 1

        # 余量：orphans 优先，再全局轮转补位
        for item in orphans:
            if len(result) >= project_n:
                break
            if not self._project_question_role_ok(
                self._plan_blob(item), state.target_role or ""
            ):
                continue
            if any(
                _is_similar_question(self._plan_blob(item), self._plan_blob(r))
                for r in result
            ):
                continue
            result.append(item)

        ptr = 0
        while len(result) < project_n:
            name = names[ptr % len(names)]
            angle = _DIVERSE_PROJECT_ANGLES[angle_idx % len(_DIVERSE_PROJECT_ANGLES)]
            angle_idx += 1
            cand = _make_slot(name, angle)
            if not any(
                _is_similar_question(self._plan_blob(cand), self._plan_blob(r))
                for r in result
            ):
                result.append(cand)
            ptr += 1
            if ptr > project_n * len(names) * 2:
                break

        return result[:project_n]

    def _seed_projects_from_chains(
        self, state: InterviewState, project_n: int
    ) -> list[dict]:
        """分题第一步：从岗位可问的项目/实习拷打链直接列题签。"""
        if project_n <= 0:
            return []
        capacity = getattr(self, "_askable_capacity", None) or {}
        askable = list(capacity.get("askable") or [])
        if not askable:
            return []

        chains_by_name = {
            str(pc.get("project") or "").strip(): pc
            for pc in (state.project_chains or [])
        }
        out: list[dict] = []
        ptr = 0
        safety = 0
        while len(out) < project_n and safety < project_n * len(askable) * 4:
            safety += 1
            item = askable[ptr % len(askable)]
            ptr += 1
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            used = sum(
                1
                for q in out
                if _question_mentions_project(
                    str(q.get("topic") or ""), str(q.get("text") or ""), name
                )
            )
            if used >= int(item.get("slots") or 1):
                continue
            pc = chains_by_name.get(name.replace("（实习）", "").split("（")[0])
            if not pc:
                for key, chain in chains_by_name.items():
                    if key in name or name in key:
                        pc = chain
                        break
            if pc:
                for c in pc.get("chains") or []:
                    if len(out) >= project_n:
                        break
                    if used >= int(item.get("slots") or 1):
                        break
                    q = str(c.get("question") or "").strip()
                    intent = str(c.get("intent") or c.get("trigger") or "项目深挖").strip()
                    if not q:
                        continue
                    blob = f"{name}：{intent} {q}"
                    if not self._project_question_role_ok(blob, state.target_role or ""):
                        continue
                    cand = {
                        "qid": "",
                        "type": "project",
                        "topic": f"{name}：{intent[:40]}"[:80],
                        "text": q[:220],
                        "rubric": "6分:能说到点 8分:有方案与取舍 9分:有失败案例与指标",
                        "original_company": "",
                    }
                    if any(
                        _is_similar_question(self._plan_blob(cand), self._plan_blob(x))
                        for x in out
                    ):
                        continue
                    out.append(cand)
                    used += 1
            elif used < int(item.get("slots") or 1):
                angle = _DIVERSE_PROJECT_ANGLES[len(out) % len(_DIVERSE_PROJECT_ANGLES)]
                topic, text = angle
                cand = {
                    "qid": "",
                    "type": "project",
                    "topic": f"{name} · {topic}"[:80],
                    "text": f"结合「{name}」说明：{text}"[:220],
                    "rubric": "6分:能说到点 8分:有方案与取舍 9分:有失败案例与指标",
                    "original_company": "",
                }
                if self._project_question_role_ok(
                    self._plan_blob(cand), state.target_role or ""
                ) and not any(
                    _is_similar_question(self._plan_blob(cand), self._plan_blob(x))
                    for x in out
                ):
                    out.append(cand)
        return out[:project_n]

    def _plan_counts(
        self, state: InterviewState, mode: str, interview_type: str
    ) -> tuple[int, int, int]:
        """Router LLM 根据目标岗位 + 简历分配项目/八股数量（项目可为 0，仅强不相关时）。"""
        n = max(3, int(state.total_rounds))
        if mode == "full":
            router = self.llm.chat_json(ROUTER_SYSTEM, self._router_user(state))
            hr_n = 1
            coding_slot = 0 if state.skip_coding else 1
            budget = max(1, n - hr_n - coding_slot)
            project_n = _clamp(int(router.get("project_count", 3)), *PROJECT_CLAMP)
            ba_gu_n = _clamp(int(router.get("ba_gu_count", 3)), *BA_GU_CLAMP)
            total_planned = project_n + ba_gu_n
            if total_planned != budget:
                if total_planned <= 0:
                    project_n, ba_gu_n = 0, budget
                else:
                    scale = budget / total_planned
                    project_n = max(0, int(round(project_n * scale)))
                    ba_gu_n = max(1, budget - project_n)
            # 有可问项目时至少留 1 道八股（预算允许且 project_n>0）
            min_ba_gu = max(1, -(-(project_n + ba_gu_n) // 5)) if project_n > 0 else 1
            if ba_gu_n < min_ba_gu and project_n > 1:
                need = min_ba_gu - ba_gu_n
                ba_gu_n = min_ba_gu
                project_n = max(0, project_n - need)
            if project_n + ba_gu_n > budget:
                ba_gu_n = max(1 if project_n > 0 else 0, budget - project_n)
            logger.info(
                "interview_router session=%s budget=%d project_n=%d ba_gu_n=%d reason=%s",
                state.session_id,
                budget,
                project_n,
                ba_gu_n,
                str(router.get("reason") or "")[:120],
            )
            return project_n, ba_gu_n, hr_n
        if interview_type == "project":
            return n, 0, 0
        if interview_type == "ba_gu":
            return 0, n, 0
        if interview_type == "hr":
            return 0, 0, n
        return 0, 0, 0

    def _build_plan(
        self, state: InterviewState, mode: str, project_n: int, ba_gu_n: int, hr_n: int
    ) -> None:
        """规划官出项目题签 + HR；八股从题库注入。拷打链不替代题单主问。"""
        raw_questions: list = []
        if project_n > 0 or hr_n > 0:
            t_planner = time.perf_counter()
            try:
                planner = self.llm.chat_json(
                    PLANNER_SYSTEM.replace("__PROJECT_COUNT__", str(project_n))
                    .replace("__HR_COUNT__", str(hr_n)),
                    self._planner_user(state),
                )
                raw_questions = planner.get("questions", [])
            except Exception as exc:  # noqa: BLE001
                raw_questions = []
                from app.services.session_guard_log import log_guard

                log_guard(
                    state.session_id,
                    "planner_llm_failed",
                    reason=type(exc).__name__,
                )
            logger.info(
                "interview_planner session=%s project_n=%d hr_n=%d "
                "raw_questions=%d elapsed_s=%.2f",
                state.session_id,
                project_n,
                hr_n,
                len(raw_questions),
                time.perf_counter() - t_planner,
            )
            from app.services.create_timing_log import step as trace_step

            trace_step(
                state.session_id,
                "planner_llm",
                duration_s=round(time.perf_counter() - t_planner, 2),
                raw_questions=len(raw_questions),
            )

        projects: list[dict] = []
        hrs: list[dict] = []
        for q in raw_questions or []:
            qtype = str(q.get("type", "project"))
            if qtype == "ba_gu":
                continue
            item = {
                "qid": "",
                "type": qtype if qtype in ("project", "hr") else "project",
                "topic": str(q.get("topic", "")),
                "text": str(q.get("key_points") or q.get("text") or ""),
                "rubric": str(q.get("rubric", "")),
                "original_company": "",
            }
            if item["type"] == "hr":
                hrs.append(item)
            else:
                projects.append(item)

        if project_n > 0:
            projects = projects[:project_n]
        else:
            projects = []
        if hr_n > 0:
            hrs = hrs[:hr_n]
            while len(hrs) < hr_n:
                hrs.append(
                    {
                        "qid": "",
                        "type": "hr",
                        "topic": "职业规划与协作",
                        "text": "职业目标,为什么选这个方向,团队协作与抗压",
                        "rubric": "",
                        "original_company": "",
                    }
                )
        else:
            hrs = []

        if project_n > 0 and not projects and mode == "full":
            projects = [
                {
                    "qid": "",
                    "type": "project",
                    "topic": "项目经历",
                    "text": "你最满意的项目、难点与方案对比",
                    "rubric": "",
                    "original_company": "",
                }
            ]

        occupied = [self._plan_blob(p) for p in projects]
        occupied.extend(str(t) for t in (state.avoid_topics or []) if str(t).strip())
        t_bagu = time.perf_counter()
        bagus = self._bagu_from_bank(ba_gu_n, occupied=occupied)
        from app.services.create_timing_log import step as trace_step

        trace_step(
            state.session_id,
            "bagu_inject",
            duration_s=round(time.perf_counter() - t_bagu, 2),
            bagu_n=len(bagus),
        )
        state.plan = projects + bagus + hrs
        # 记住配额：去重后空位按题型重新出，禁止用八股填项目坑
        self._plan_project_n = int(project_n)
        self._plan_ba_gu_n = int(ba_gu_n)
        self._plan_hr_n = int(hr_n)

        # 全流程模式固定一道算法题：插在 HR 题之前（题库无可判题时跳过；可自定义关掉）
        if mode == "full" and not state.skip_coding:
            coding = pick_coding_question(exclude_slugs=self._avoid_coding_slugs(state))
            if coding:
                hr_idx = next(
                    (i for i, q in enumerate(state.plan) if q["type"] == "hr"),
                    len(state.plan),
                )
                state.plan.insert(
                    hr_idx,
                    {
                        "qid": "",
                        "type": "coding",
                        "topic": f"算法题：{coding['title']}（{coding['difficulty']}）",
                        "text": coding["description"],
                        "slug": coding["slug"],
                        "rubric": "",
                    },
                )

        # 硬约束：skip_coding 时清掉任何 coding 题（含误插入）
        if state.skip_coding:
            state.plan = [q for q in state.plan if q.get("type") != "coding"]

        # 硬约束：规划后对照历史库做相似/相同检查，命中剔除；空位按原题型重新出
        target_n = max(3, int(state.total_rounds))
        state.plan = self._dedupe_plan(state.plan, state.avoid_topics or [])
        state.plan = self._top_up_plan(state, target_n, mode)
        cleaned = self._dedupe_plan(state.plan, state.avoid_topics or [])
        if len(cleaned) < len(state.plan):
            state.plan = cleaned
            state.plan = self._top_up_plan(state, target_n, mode)

        if not state.plan:
            from app.services.session_guard_log import log_guard

            state.plan = self._fallback_plan(mode)
            log_guard(state.session_id, "fallback_plan", mode=mode, plan_len=len(state.plan))
            if state.skip_coding:
                state.plan = [q for q in state.plan if q.get("type") != "coding"]

        for i, q in enumerate(state.plan):
            q["qid"] = f"q{i + 1}"
        state.per_question = {q["qid"]: PerQuestion().to_dict() for q in state.plan}

    def _insert_before_types(self, plan: list[dict], item: dict, types: tuple[str, ...]) -> None:
        insert_at = next((i for i, p in enumerate(plan) if p.get("type") in types), len(plan))
        plan.insert(insert_at, item)

    def _plan_blob(self, q: dict) -> str:
        return f"{q.get('topic', '')} {q.get('text', '')}".strip()

    def _ok_new_item(self, blob: str, avoid: list[str], plan: list[dict]) -> bool:
        if not blob or len(blob.strip()) < 8:
            return False
        if _looks_like_vague_orchestration(blob):
            return False
        if _conflicts_historical_question(blob, avoid):
            return False
        if any(_is_similar_question(blob, self._plan_blob(p)) for p in plan):
            return False
        return True

    def _ok_new_bagu(self, blob: str, avoid: list[str], plan: list[dict]) -> bool:
        if not self._ok_new_item(blob, avoid, plan):
            return False
        occupied = list(avoid) + [self._plan_blob(p) for p in plan]
        return not _conflicts_bagu_knowledge(blob, occupied)

    def _regenerate_project_items(
        self, state: InterviewState, need: int, avoid: list[str], plan: list[dict]
    ) -> list[dict]:
        """去重空出的项目位：重新出项目深挖题（拷打链 / 简历点名 / LLM / 差异化角度）。

        严禁用八股凑数。
        """
        if need <= 0:
            return []
        out: list[dict] = []
        local_avoid = list(avoid)

        def _accept(topic: str, text: str) -> bool:
            blob = f"{topic} {text}".strip()
            if not self._ok_new_item(blob, local_avoid, plan + out):
                return False
            out.append(
                {
                    "qid": "",
                    "type": "project",
                    "topic": topic[:80],
                    "text": text[:220],
                    "rubric": "6分:能说到点 8分:有方案与取舍 9分:有失败案例与指标",
                    "original_company": "",
                }
            )
            local_avoid.append(blob)
            return True

        # 1) 拷打链 → 点名项目的具体追问（岗位相关项目优先）
        from app.services.job_roles import resume_project_names

        chain_order = resume_project_names(
            state.profile or {}, state.target_role or "", limit=3
        )
        chains_by_name = {
            str(pc.get("project") or "").strip(): pc
            for pc in (state.project_chains or [])
        }
        ordered_chains = [
            chains_by_name[n] for n in chain_order if n in chains_by_name
        ] + [
            pc
            for pc in (state.project_chains or [])
            if str(pc.get("project") or "").strip() not in chain_order
        ]
        for pc in ordered_chains:
            if len(out) >= need:
                break
            pname = str(pc.get("project") or "").strip() or "简历项目"
            for c in pc.get("chains") or []:
                if len(out) >= need:
                    break
                q = str(c.get("question") or "").strip()
                intent = str(c.get("intent") or c.get("trigger") or "项目深挖").strip()
                if not q:
                    continue
                _accept(f"{pname}：{intent[:40]}", q)

        # 2) 简历项目名 × 差异化角度（按岗位相关度排序后轮转，避免只问第一个项目）
        profile = state.profile or {}
        from app.services.job_roles import resume_project_names

        resume_projects = resume_project_names(
            profile, state.target_role or "", limit=3
        )
        angle_i = 0
        proj_i = 0
        while len(out) < need and resume_projects:
            pname = resume_projects[proj_i % len(resume_projects)]
            topic, text = _DIVERSE_PROJECT_ANGLES[angle_i % len(_DIVERSE_PROJECT_ANGLES)]
            angle_i += 1
            proj_i += 1
            _accept(f"{pname} · {topic}", f"结合项目「{pname}」说明：{text}")

        # 3) LLM 按避让列表重出（只要项目题）
        still = need - len(out)
        if still > 0 and self.llm is not None:
            for item in self._llm_regen_projects(state, still, local_avoid, plan + out):
                if len(out) >= need:
                    break
                out.append(item)
                local_avoid.append(self._plan_blob(item))

        # 4) 最后才用未点名的差异化角度（仍是 project，不是八股）
        for topic, text in _DIVERSE_PROJECT_ANGLES:
            if len(out) >= need:
                break
            _accept(topic, text)

        return out[:need]

    def _llm_regen_projects(
        self,
        state: InterviewState,
        n: int,
        avoid: list[str],
        plan: list[dict],
    ) -> list[dict]:
        """让规划官按避让列表重出 n 道点名简历项目的题签。"""
        if n <= 0:
            return []
        from app.prompts.interview import PLANNER_SYSTEM

        avoid_sample = "；".join(str(t)[:70] for t in avoid[:40] if str(t).strip())
        user = (
            self._planner_user(state)
            + f"\n\n【硬性重出】历史/本场已覆盖角度必须避开：{avoid_sample or '（无）'}\n"
            f"请只输出 {n} 道 type=project 的全新项目深挖题签；"
            "每道必须点名简历里的具体项目名，换尚未问过的落地角度"
            "（失败重试、一致性、评测、权限、延迟成本、灰度等）；"
            "禁止八股，禁止空泛编排。"
        )
        try:
            raw = self.llm.chat_json(
                PLANNER_SYSTEM.replace("__PROJECT_COUNT__", str(n)).replace(
                    "__HR_COUNT__", "0"
                ),
                user,
                max_retries=1,
            )
        except Exception:  # noqa: BLE001
            return []
        items: list[dict] = []
        for q in raw.get("questions") or []:
            if len(items) >= n:
                break
            if str(q.get("type") or "project") == "ba_gu":
                continue
            topic = str(q.get("topic") or "").strip()
            text = str(q.get("key_points") or q.get("text") or "").strip()
            blob = f"{topic} {text}"
            if not self._ok_new_item(blob, avoid, plan + items):
                continue
            items.append(
                {
                    "qid": "",
                    "type": "project",
                    "topic": topic or "项目深挖",
                    "text": text,
                    "rubric": str(q.get("rubric") or ""),
                    "original_company": "",
                }
            )
        return items

    def _top_up_plan(self, state: InterviewState, target_n: int, mode: str) -> list[dict]:
        """去重后补齐：按原配额重新出对应题型。

        - 项目空位 → 重新出项目（拷打链/简历点名/LLM），禁止八股填坑
        - 八股空位 → 另抽不同八股
        - 仍不足轮次 → 继续重出项目，不用八股滥竽充数
        """
        plan = list(state.plan or [])
        if len(plan) >= target_n:
            return plan[:target_n]

        project_quota = int(getattr(self, "_plan_project_n", 0) or 0)
        ba_gu_quota = int(getattr(self, "_plan_ba_gu_n", 0) or 0)
        has_askable = bool(
            (getattr(self, "_askable_capacity", None) or {}).get("has_askable")
        )
        # 有可问项目时才保底补项目；岗位无可问素材时允许全场八股
        if mode == "full" and project_quota <= 0 and has_askable:
            project_quota = max(1, min(3, target_n // 3))

        avoid = [str(t) for t in (state.avoid_topics or []) if str(t).strip()]
        for q in plan:
            avoid.append(self._plan_blob(q))

        def _count(t: str) -> int:
            return sum(1 for p in plan if p.get("type") == t)

        # 1) 补项目到配额
        need_proj = max(0, project_quota - _count("project"))
        if need_proj > 0:
            for item in self._regenerate_project_items(state, need_proj, avoid, plan):
                self._insert_before_types(plan, item, ("ba_gu", "hr", "coding"))
                avoid.append(self._plan_blob(item))

        # 2) 只补「八股配额」缺口：另抽八股，不得拿来填项目空
        need_bagu = max(0, ba_gu_quota - _count("ba_gu"))
        still_for_bagu = min(need_bagu, max(0, target_n - len(plan)))
        if still_for_bagu > 0:
            occupied = list(avoid) + [self._plan_blob(p) for p in plan]
            for h in self._bagu_from_bank(still_for_bagu + 3, occupied=occupied):
                if still_for_bagu <= 0 or len(plan) >= target_n:
                    break
                blob = self._plan_blob(h)
                if not self._ok_new_bagu(blob, avoid, plan):
                    continue
                self._insert_before_types(plan, h, ("hr",))
                avoid.append(blob)
                still_for_bagu -= 1

        # 3) 仍不足：全流程优先继续重出项目；专项八股场 / 项目耗尽才八股重抽兜底
        while len(plan) < target_n:
            gap = target_n - len(plan)
            prefer_project = project_quota > 0 and _count("project") < project_quota
            if prefer_project:
                more = self._regenerate_project_items(state, gap, avoid, plan)
                if more:
                    for item in more:
                        if len(plan) >= target_n:
                            break
                        self._insert_before_types(plan, item, ("ba_gu", "hr", "coding"))
                        avoid.append(self._plan_blob(item))
                    continue
            filled = False
            occupied = list(avoid) + [self._plan_blob(p) for p in plan]
            for h in self._bagu_from_bank(gap + 2, occupied=occupied):
                if len(plan) >= target_n:
                    break
                blob = self._plan_blob(h)
                if not self._ok_new_bagu(blob, avoid, plan):
                    continue
                self._insert_before_types(plan, h, ("hr",))
                avoid.append(blob)
                filled = True
            if not filled:
                break

        return plan[:target_n]

    def _bagu_from_bank(
        self, n: int, occupied: list[str] | None = None
    ) -> list[dict]:
        """八股：召回候选池 → 面试官遴选；同一题库条目/换句不重复，允许同类考点换角度。"""
        if n <= 0:
            return []
        from app.services import knowledge_retrieval as kr
        from app.services.job_roles import all_roles, company_display_name

        roles = list(getattr(self, "_plan_roles", None) or [])
        # 未显式选岗位时只用主推断岗，避免 Java+Agent 双栈八股乱炖
        if not getattr(self, "_plan_role_explicit", False) and len(roles) > 1:
            roles = roles[:1]
        skills = list(getattr(self, "_plan_skills", None) or [])
        company_id = getattr(self, "_plan_company_id", None)
        asked = set(getattr(self, "_asked_norms", None) or set())
        display = (getattr(self, "_company_display", None) or "").strip()
        if not display and company_id:
            display = company_display_name(company_id) or ""
        occupied_blobs = [str(t) for t in (occupied or []) if str(t).strip()]

        pool_n = max(n * 10, 24)
        candidates = kr.pick_bagu_questions(
            roles=roles or None,
            company=company_id,
            skills=skills or None,
            asked_norms=asked,
            n=pool_n,
        )
        candidates = [
            h
            for h in candidates
            if not kr._is_noisy(h)
            and str(h.get("question") or "").strip()
            and not self._looks_like_meta_bagu(str(h.get("question") or ""))
            and not _conflicts_bagu_knowledge(str(h.get("question") or ""), occupied_blobs)
        ]
        # 标题型条目靠后：完整问句优先进候选前排，减少 LLM/启发式照念标题
        candidates.sort(
            key=lambda h: (
                0 if self._is_spoken_question(str(h.get("question") or "")) else 1,
                0 if (h.get("answer") or "").strip() else 1,
            )
        )
        candidates = self._diversify_bagu_pool(candidates, occupied_blobs, max(n * 5, 10))
        if not candidates:
            return []

        role_names = []
        catalog = all_roles()
        for rid in roles:
            role_names.append(str((catalog.get(rid) or {}).get("name") or rid))
        target_label = "、".join(role_names) if role_names else "（未指定，按简历主技术栈）"

        selected = self._select_bagu_with_llm(
            candidates, n, target_label, occupied_blobs
        )
        if not selected:
            selected = self._bagu_heuristic_pick(candidates, n, occupied_blobs)

        items: list[dict] = []
        picked_blobs: list[str] = list(occupied_blobs)
        for h, spoken, topic, key_points in selected:
            qtext = str(h.get("question") or "").strip()
            if not qtext:
                continue
            ans = str(h.get("answer") or "").strip()
            src_cid = str(h.get("company") or "").strip()
            if company_id and src_cid == company_id:
                oc = display or company_display_name(src_cid) or src_cid
            elif src_cid:
                oc = company_display_name(src_cid) or src_cid
            else:
                oc = ""
            spoken_q = self._ensure_spoken_question(
                self._strip_catalog_prefix(spoken or qtext), qtext
            )
            bank_q = self._strip_catalog_prefix(qtext) or qtext
            # 仍是标题且无法改成问句 → 丢弃
            if not self._is_spoken_question(spoken_q):
                continue
            blob = f"{topic or ''} {spoken_q} {bank_q}"
            if _conflicts_bagu_knowledge(blob, picked_blobs):
                continue
            items.append(
                {
                    "qid": "",
                    "type": "ba_gu",
                    "topic": topic or self._topic_from_bank_question(spoken_q),
                    "text": spoken_q,
                    "key_points": key_points or "",
                    "rubric": "6分:基本概念清楚 8分:原理与场景 9分:工程实践与取舍",
                    "original_company": oc,
                    "bank_question": bank_q,
                    "bank_answer": ans,
                    "from_bank": True,
                    "source_file": h.get("source_file") or "",
                }
            )
            picked_blobs.append(blob)
            if len(items) >= n:
                break
        # LLM 选重了知识点时，用启发式从剩余池补齐不同簇
        if len(items) < n:
            extra = self._bagu_heuristic_pick(candidates, n - len(items), picked_blobs)
            have = {str(x.get("bank_question") or "") for x in items}
            for h, spoken, topic, key_points in extra:
                qtext = self._strip_catalog_prefix(str(h.get("question") or "").strip())
                if not qtext or qtext in have:
                    continue
                spoken_q = self._ensure_spoken_question(spoken or qtext, qtext)
                if not self._is_spoken_question(spoken_q):
                    continue
                blob = f"{topic or ''} {spoken_q} {qtext}"
                if _conflicts_bagu_knowledge(blob, picked_blobs):
                    continue
                src_cid = str(h.get("company") or "").strip()
                if company_id and src_cid == company_id:
                    oc = display or company_display_name(src_cid) or src_cid
                elif src_cid:
                    oc = company_display_name(src_cid) or src_cid
                else:
                    oc = ""
                items.append(
                    {
                        "qid": "",
                        "type": "ba_gu",
                        "topic": topic or self._topic_from_bank_question(spoken_q),
                        "text": spoken_q,
                        "key_points": key_points or "",
                        "rubric": "6分:基本概念清楚 8分:原理与场景 9分:工程实践与取舍",
                        "original_company": oc,
                        "bank_question": qtext,
                        "bank_answer": str(h.get("answer") or "").strip(),
                        "from_bank": True,
                        "source_file": h.get("source_file") or "",
                    }
                )
                picked_blobs.append(blob)
                if len(items) >= n:
                    break
        return items[:n]

    @staticmethod
    def _diversify_bagu_pool(
        candidates: list[dict], occupied: list[str], limit: int
    ) -> list[dict]:
        """候选池去掉近重复条目，保留不同问法（含同技术换角度）。"""
        if not candidates:
            return []
        picked: list[dict] = []
        occupied_now = list(occupied)
        leftovers: list[dict] = []
        for h in candidates:
            q = str(h.get("question") or "")
            if _conflicts_bagu_knowledge(q, occupied_now):
                leftovers.append(h)
                continue
            picked.append(h)
            occupied_now.append(q)
            if len(picked) >= limit:
                return picked
        for h in leftovers:
            if len(picked) >= limit:
                break
            q = str(h.get("question") or "")
            if any(_is_similar_question(q, str(x.get("question") or "")) for x in picked):
                continue
            picked.append(h)
        return picked

    def _select_bagu_with_llm(
        self,
        candidates: list[dict],
        n: int,
        target_label: str,
        occupied: list[str] | None = None,
    ) -> list[tuple[dict, str, str, str]]:
        """从候选中让 LLM 选 n 道并润色口头题面；校验 index，失败返回空。"""
        if not candidates or n <= 0:
            return []
        occupied_blobs = [str(t) for t in (occupied or []) if str(t).strip()]
        lines = []
        for i, h in enumerate(candidates):
            q = str(h.get("question") or "").strip()
            roles = ",".join(h.get("roles") or [])
            company = h.get("company") or ""
            lines.append(f"{i}. [{company}|{roles}] {q}")
        occupied_txt = "；".join(t[:80] for t in occupied_blobs[:20]) or "（无）"
        user = (
            f"N={n}\n【目标岗位】{target_label}\n"
            f"【本场已问/将问，不要再选同一条或换句重复】\n{occupied_txt}\n\n"
            "【候选八股题】\n"
            + "\n".join(lines)
            + "\n\n请按规则选出最多 N 道并给出口头问法；不要选同一条/换句重复的候选，换角度可以。"
        )
        try:
            result = self.llm.chat_json(BAGU_SELECT_SYSTEM, user)
        except Exception:  # noqa: BLE001
            return []

        picked: list[tuple[dict, str, str, str]] = []
        seen_idx: set[int] = set()
        picked_blobs: list[str] = list(occupied_blobs)
        for row in result.get("selected") or []:
            if len(picked) >= n:
                break
            try:
                idx = int(row.get("index"))
            except (TypeError, ValueError):
                continue
            if idx in seen_idx or idx < 0 or idx >= len(candidates):
                continue
            h = candidates[idx]
            qtext = str(h.get("question") or "").strip()
            spoken = self._ensure_spoken_question(
                self._strip_catalog_prefix(
                    str(row.get("spoken") or "").strip() or qtext
                ),
                qtext,
            )
            topic = str(row.get("topic") or "").strip()
            key_points = str(row.get("key_points") or "").strip()
            if self._looks_like_meta_bagu(spoken) or self._looks_like_meta_bagu(qtext):
                continue
            if not self._is_spoken_question(spoken):
                continue
            blob = f"{topic} {spoken} {qtext}"
            if _conflicts_bagu_knowledge(blob, picked_blobs):
                continue
            seen_idx.add(idx)
            picked.append((h, spoken, topic, key_points))
            picked_blobs.append(blob)
        return picked

    def _bagu_heuristic_pick(
        self,
        candidates: list[dict],
        n: int,
        occupied: list[str] | None = None,
    ) -> list[tuple[dict, str, str, str]]:
        """LLM 不可用时：丢掉元问题后按题库条目去重取。"""
        out: list[tuple[dict, str, str, str]] = []
        occupied_now = [str(t) for t in (occupied or []) if str(t).strip()]
        for h in candidates:
            raw = str(h.get("question") or "").strip()
            if not raw or self._looks_like_meta_bagu(raw):
                continue
            q = self._ensure_spoken_question(self._strip_catalog_prefix(raw), raw)
            if not self._is_spoken_question(q):
                continue
            blob = f"{q} {raw}"
            if _conflicts_bagu_knowledge(blob, occupied_now):
                continue
            out.append((h, q, self._topic_from_bank_question(q), ""))
            occupied_now.append(blob)
            if len(out) >= n:
                break
        return out


    @staticmethod
    def _strip_catalog_prefix(text: str) -> str:
        """去掉题库目录编号（Q1: / Q2. 等），避免原样念给候选人。"""
        s = (text or "").strip()
        s = re.sub(r"^Q\s*\d+\s*[:：.、\)\]】]\s*", "", s, flags=re.IGNORECASE)
        return s.strip() or (text or "").strip()

    @staticmethod
    def _is_spoken_question(text: str) -> bool:
        """是否像面试官口头完整问句（非知识点标题）。"""
        t = (text or "").strip()
        if len(t) < 8:
            return False
        if t.endswith(("？", "?")):
            return True
        return any(
            w in t
            for w in (
                "吗",
                "呢",
                "如何",
                "怎么",
                "怎样",
                "什么",
                "哪些",
                "为什么",
                "为何",
                "请说明",
                "请谈谈",
                "请讲",
                "说说",
                "有什么区别",
                "怎么实现",
                "如何实现",
            )
        )

    @classmethod
    def _ensure_spoken_question(cls, spoken: str, bank_q: str) -> str:
        """标题型题面改成可问出口的完整问句；已是问句则原样返回。"""
        s = cls._strip_catalog_prefix(spoken or bank_q)
        if cls._is_spoken_question(s):
            return s
        core = cls._strip_catalog_prefix(bank_q) or s
        core = core.rstrip("。.!！；;，,")
        if not core:
            return s
        return f"请结合原理和工程实践，谈谈{core}？"

    @staticmethod
    def _looks_like_meta_bagu(text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return True
        if re.search(r"[A-Za-z]{4,}", t) and not re.search(r"[\u4e00-\u9fff]", t):
            return True
        low = t.lower()
        if "interview reference" in low:
            return True
        if "面试" in t and any(w in t for w in ("重点", "知识点是", "怎么准备", "如何准备")):
            return True
        if any(w in t for w in ("哪些知识点是重点", "题库合集", "复习路线")):
            return True
        return False

    @staticmethod
    def _topic_from_bank_question(question: str) -> str:
        s = InterviewEngine._strip_catalog_prefix(question or "")
        s = s.rstrip("？?。.!！")
        if len(s) <= 28:
            return s or "八股知识"
        return s[:26].rstrip("，,、 ：:") + "…"

    def _annotate_original_company(self, state: InterviewState) -> None:
        """把企业原题标记落到 plan.original_company（展示名），供报告金色徽标。

        - 规划官已填的：规范化为中文展示名
        - 未填但检索命中企业原题且题签高度相关：回填展示名（不靠 LLM 自行发明）
        """
        from app.services.job_roles import company_display_name

        display = (getattr(self, "_company_display", None) or "").strip()
        hits = list(getattr(self, "_enterprise_hits", None) or [])
        if not display and state.target_company:
            display = company_display_name(state.target_company) or state.target_company.strip()

        for q in state.plan:
            raw = str(q.get("original_company") or "").strip()
            if raw:
                q["original_company"] = company_display_name(raw) or raw
                continue
            if not display or not hits:
                q["original_company"] = ""
                continue
            blob = f"{q.get('topic') or ''} {q.get('text') or ''}"
            matched = False
            for h in hits:
                if self._company_hit_overlap(blob, str(h.get("question") or "")):
                    q["original_company"] = display
                    matched = True
                    break
            if not matched:
                q["original_company"] = ""

    @staticmethod
    def _company_hit_overlap(plan_blob: str, hit_question: str) -> bool:
        """题签与企业原题是否足够相关（用于回填徽标，宁缺毋滥）。"""
        a = re.sub(r"\W+", "", (plan_blob or "").lower())
        b = re.sub(r"\W+", "", (hit_question or "").lower())
        if len(a) < 4 or len(b) < 4:
            return False
        # 连续 4 字命中，或 2-gram 交集够多
        if any(a[i : i + 4] in b for i in range(len(a) - 3)):
            return True
        ga = {a[i : i + 2] for i in range(len(a) - 1)}
        gb = {b[i : i + 2] for i in range(len(b) - 1)}
        return len(ga & gb) >= 4

    def _avoid_coding_slugs(self, state: InterviewState) -> set[str]:
        slugs: set[str] = set()
        for t in state.avoid_topics or []:
            s = str(t)
            if s.startswith("coding:"):
                slugs.add(s.split(":", 1)[1].strip())
        return slugs

    def _dedupe_plan(self, plan: list[dict], avoid_topics: list) -> list[dict]:
        """剔除与历史冲突、以及本场已留同题/换句。八股按题库条目去重，不整类封杀。保底至少 1 题。"""
        kept: list[dict] = []
        hist = [str(t) for t in (avoid_topics or []) if str(t).strip()]
        siblings: list[str] = []
        for q in plan:
            blob = f"{q.get('topic', '')} {q.get('text', '')} {q.get('bank_question', '')}".strip()
            if blob and _conflicts_historical_question(blob, hist):
                continue
            if q.get("type") == "ba_gu":
                if blob and _conflicts_bagu_knowledge(blob, siblings + hist):
                    continue
            elif blob and _conflicts_plan_sibling(blob, siblings):
                continue
            kept.append(q)
            if blob:
                siblings.append(blob)
            topic = str(q.get("topic") or "").strip()
            if topic:
                siblings.append(topic)
        return kept if kept else plan[:1]

    def _fallback_plan(self, mode: str) -> list[dict]:
        # 尽量仍从八股库抽 1 道；抽不到再给占位（极端空库）
        bagus = self._bagu_from_bank(1)
        if mode == "full":
            fallback = [
                {"type": "project", "topic": "项目经历", "text": "你最满意的项目、难点与方案对比", "rubric": "", "original_company": ""},
                *(
                    bagus
                    or [
                        {
                            "type": "ba_gu",
                            "topic": "核心技术栈",
                            "text": "请结合你的目标岗位，说明一项核心技术的原理与适用场景。",
                            "rubric": "",
                            "original_company": "",
                        }
                    ]
                ),
                {"type": "hr", "topic": "职业规划", "text": "职业规划与团队协作", "rubric": "", "original_company": ""},
            ]
        else:
            fallback = [
                {"type": "project", "topic": "项目经历", "text": "项目细节、难点、量化指标", "rubric": "", "original_company": ""},
                *(
                    bagus
                    or [
                        {
                            "type": "ba_gu",
                            "topic": "技术基础",
                            "text": "请说明一项核心知识点及其应用场景。",
                            "rubric": "",
                            "original_company": "",
                        }
                    ]
                ),
            ]
        return [
            {
                "qid": f"q{i + 1}",
                "type": q["type"],
                "topic": q["topic"],
                "text": q["text"],
                "rubric": q.get("rubric", ""),
                "original_company": q.get("original_company", ""),
                **(
                    {
                        "bank_question": q["bank_question"],
                        "bank_answer": q.get("bank_answer", ""),
                        "from_bank": True,
                    }
                    if q.get("bank_question")
                    else {}
                ),
            }
            for i, q in enumerate(fallback)
        ]

    # ---------- 自我介绍回答 → 直接出第一题（计划已在创建时完成） ----------

    def handle_intro(self, state: InterviewState, answer: str):
        if not state.plan:
            raise ValueError("面试尚未规划")
        state.intro_text = answer
        state.history.append({"role": "candidate", "text": answer})
        state.stage = "ASKING"

        message = self._ask_question(state)
        state.history.append({"role": "interviewer", "text": message})
        return state, message

    # ---------- 正式面试回答 → 追问官 + 评分官并行 → 追问或下一题 ----------

    def handle_answer(self, state: InterviewState, answer: str):
        if not state.plan:
            raise ValueError("面试尚未规划")
        qid = f"q{state.cursor + 1}"
        pq = state.per_question[qid]
        clipped = answer[:ANSWER_TRUNCATE]
        pq["answers"].append(clipped)
        state.history.append({"role": "candidate", "text": answer})
        state.rounds_used += 1

        score_ctx = self._score_context(state, qid, answer_only=clipped)
        follow_ctx = self._question_context(state, qid)
        judge, score = self.llm.chat_json_many(
            [
                (FOLLOW_UP_SYSTEM, follow_ctx + "\n\n【候选人最新回答】\n" + answer),
                (SCORE_SYSTEM, score_ctx),
            ]
        )
        sc, strengths, weaknesses = sanitize_score_fields(
            [clipped],
            score.get("score", 5),
            score.get("strengths"),
            score.get("weaknesses"),
        )
        raw_sc = score.get("score", 5)
        try:
            raw_sc_f = float(raw_sc)
        except (TypeError, ValueError):
            raw_sc_f = 5.0
        if raw_sc_f > NON_ANSWER_MAX_SCORE and sc <= NON_ANSWER_MAX_SCORE + 0.01:
            from app.services.session_guard_log import log_guard

            log_guard(
                state.session_id,
                "score_capped",
                qid=qid,
                score_in=round(raw_sc_f, 1),
                score_out=sc,
            )
        raw_st = [str(x).strip() for x in (score.get("strengths") or []) if str(x).strip()]
        if raw_st and not strengths:
            from app.services.session_guard_log import log_guard

            log_guard(state.session_id, "strengths_cleared", qid=qid, raw_n=len(raw_st))
        self._close_turn(pq, clipped, sc, strengths, weaknesses)
        # 题级分取各轮均分，便于摘要与旧逻辑
        turn_scores = [float(t["score"]) for t in pq.get("turns") or [] if t.get("score") is not None]
        pq["score"] = round(sum(turn_scores) / len(turn_scores), 1) if turn_scores else sc
        pq["strengths"] = strengths
        pq["weaknesses"] = weaknesses

        needs_follow = bool(judge.get("needs_follow_up", False))
        # 跳过/敷衍不作答：引擎强制不追问，避免纠缠空答
        if is_non_answer(pq.get("answers")) or is_non_answer([answer]):
            needs_follow = False
            from app.services.session_guard_log import log_guard

            log_guard(state.session_id, "non_answer_no_followup", qid=qid)
        fq = str(judge.get("follow_up_question", "")).strip() if needs_follow else ""
        if fq:
            prior_qs = [
                str(t.get("question") or "").strip()
                for t in (pq.get("turns") or [])
                if str(t.get("question") or "").strip()
            ]
            # 本轮刚答完的题干也在 turns 末条；再加会话里本题更早的面试官句兜底
            if _is_repeat_followup(fq, prior_qs, pq.get("answers") or []):
                from app.services.session_guard_log import log_guard

                log_guard(
                    state.session_id,
                    "followup_repeat_rejected",
                    qid=qid,
                    follow_q=fq[:80],
                )
                fq = ""
                needs_follow = False
        if (
            needs_follow
            and fq
            and pq["followups_so_far"] < MAX_FOLLOW_UPS_PER_QUESTION
            and state.rounds_used < state.total_rounds
        ):
            pq["followups_so_far"] += 1
            pq["pending_asked_text"] = fq
            pq["pending_reference_answer"] = str(
                judge.get("follow_up_reference_answer") or ""
            ).strip()
            state.history.append({"role": "interviewer", "text": fq})
            return state, fq

        pq["summary"] = self._make_summary(state, qid, pq)
        state.cursor += 1
        if state.cursor < len(state.plan):
            message = self._ask_question(state)
            state.history.append({"role": "interviewer", "text": message})
            return state, message

        # 全部主问题完成 → 进入汇总（不再反问）
        state.stage = "SUMMARIZING"
        state.history.append({"role": "interviewer", "text": SUMMARIZING_TEXT})
        return state, SUMMARIZING_TEXT

    # ---------- 算法题提交 → 记分并推进 ----------

    def handle_coding(self, state: InterviewState, verdict: str, score: float, review: dict):
        """算法题提交后的引擎推进：评分入账、cursor+1、出下一题或进反问环节。

        verdict: 判题结果（accepted/wrong_answer/timeout/runtime_error）
        score: AI 评审给出的 1-10 分
        review: AI 评审 dict（highlight/issues 进 strengths/weaknesses 供终评官参考）
        """
        q = state.plan[state.cursor]
        qid = f"q{state.cursor + 1}"
        pq = state.per_question[qid]
        ans = f"[代码提交] 判定：{verdict}"
        pq["answers"].append(ans)
        pq["score"] = float(score)
        highlight = str(review.get("highlight", "")).strip()
        issues = [str(x) for x in review.get("issues", []) if str(x).strip()]
        pq["strengths"] = [highlight] if highlight else []
        pq["weaknesses"] = issues[:2]
        if not pq.get("pending_asked_text"):
            pq["pending_asked_text"] = q.get("topic") or "算法题"
        self._close_turn(pq, ans, float(score), pq["strengths"], pq["weaknesses"])
        state.history.append({"role": "candidate", "text": f"[算法题作答] 判定：{verdict}"})
        state.rounds_used += 1
        pq["summary"] = self._make_summary(state, qid, pq)
        state.cursor += 1
        if state.cursor < len(state.plan):
            message = self._ask_question(state)
            state.history.append({"role": "interviewer", "text": message})
            return state, message
        state.stage = "SUMMARIZING"
        state.history.append({"role": "interviewer", "text": SUMMARIZING_TEXT})
        return state, SUMMARIZING_TEXT

    # ---------- 汇总终评（跳过反问） ----------

    def finish_interview(self, state: InterviewState):
        state.stage = "FINISHED"
        report = self.llm.chat_json(FINAL_REPORT_SYSTEM, self._report_user(state))
        report = self._sanitize_report(state, report)
        return state, report

    # ---------- 反问回答 → 终评（兼容旧会话） ----------

    def handle_ask_back(self, state: InterviewState, answer: str):
        if answer.strip():
            state.history.append({"role": "candidate", "text": answer})
        return self.finish_interview(state)

    # ---------- 内部：出题 / 上下文构造 ----------

    def _close_turn(
        self,
        pq: dict,
        answer: str,
        score: float,
        strengths: list,
        weaknesses: list,
    ) -> None:
        """把当前 pending 问题与本轮作答落成独立 turn（报告拆条用）。"""
        turns = pq.setdefault("turns", [])
        asked = str(pq.get("pending_asked_text") or "").strip()
        ref = str(pq.get("pending_reference_answer") or "").strip()
        turns.append(
            {
                "question": asked,
                "answer": answer,
                "score": float(score),
                "strengths": list(strengths or []),
                "weaknesses": list(weaknesses or []),
                "reference_answer": ref,
                "is_followup": len(turns) > 0,
            }
        )
        pq["pending_asked_text"] = ""
        pq["pending_reference_answer"] = ""

    def _ask_question(self, state: InterviewState) -> str:
        q = state.plan[state.cursor]
        qid = q["qid"]
        pq = state.per_question[qid]
        if q["type"] == "coding":
            # 算法题：题面在编码界面展示，面试官只做简短引导，不重复题面
            message = (
                f"接下来是一道算法题：{q['topic']}。"
                "请在编辑器里完成实现，先点「运行」自测示例，确认无误后点「提交」。"
            )
            pq["pending_asked_text"] = message
            pq["pending_reference_answer"] = ""
            return message
        # 八股库真题：用规划阶段润色后的口头题面；参考答案优先题库要点
        bank_q = str(q.get("bank_question") or "").strip()
        if q.get("type") == "ba_gu" and bank_q:
            message = str(q.get("text") or bank_q).strip() or bank_q
            pq["pending_asked_text"] = message
            pq["pending_reference_answer"] = str(q.get("bank_answer") or "").strip()
            return message
        past = self._past_summaries(state)
        chain_block = ""
        if q["type"] == "project" and state.project_chains:
            from app.services.project_cross import chain_block_for

            # 优先找 topic 里带项目名的拷打链，找不到则全量注入（提示只取相关）
            matched = None
            for pc in state.project_chains:
                if pc.get("project") and pc["project"] in q["topic"]:
                    matched = pc
                    break
            if matched is not None:
                chain_block = "\n\n【该项目拷打链——真实面试会怎么追问，可参考组织提问】\n" + chain_block_for(
                    [matched], matched["project"]
                )
            elif state.project_chains:
                chain_block = "\n\n【候选人的项目拷打链（仅当与本题相关时参考）】\n" + "\n".join(
                    chain_block_for([pc], pc["project"])
                    for pc in state.project_chains
                )
        user = (
            self._ctx_block(state)
            + "\n\n【候选人近期表现评估】\n"
            + self._performance_block(state)
            + "\n\n【前面已回答的问题与回答摘要】\n"
            + (past if past else "（无）")
            + "\n\n【已问过的主题，禁止重复提问】\n"
            + ("、".join(t["topic"] for t in state.plan[: state.cursor]) or "（无）")
            + chain_block
            + "\n\n【简历可引用白名单——仅这些才能说「简历中写到」】\n"
            + self._resume_cite_whitelist(state)
            + "\n\n【现在请向候选人提出下面这道题】\n"
            + f"主题：{q['topic']}\n关键问点（只选其中 1 个来问，禁止堆成清单）：{q['text']}"
            + (f"\n评分参考（rubric）：{q['rubric']}" if q.get("rubric") else "")
            + "\n要求：只围绕一个关键问点问出一道具体、自然的问题；严禁把多个问点串成一长串；"
            "若本题考点不在白名单内，禁止说简历提到过，直接按目标岗位提问即可"
        )
        raw = self.llm.chat_json(ASK_QUESTION_SYSTEM, user)
        if not isinstance(raw, dict):
            raw = {}
        question = str(raw.get("question") or "").strip()
        if not question:
            # 兼容旧 FakeLlm / 异常回退
            question = self.llm.chat_text(INTERVIEWER_SYSTEM, user)
        question = self._sanitize_resume_claim(question, state)
        # 出题硬去重：规划题签过了，口头现编仍可能撞历史换句题 / 空泛编排死循环
        asked_blobs = [
            str(t) for t in (state.avoid_topics or []) if str(t).strip()
        ] + [
            str(m.get("text") or "")
            for m in state.history
            if m.get("role") == "interviewer"
        ]
        need_retry = False
        if asked_blobs and _conflicts_historical_question(question, asked_blobs):
            need_retry = True
        if _looks_like_vague_orchestration(question):
            need_retry = True
        if need_retry:
            from app.services.session_guard_log import log_guard

            log_guard(
                state.session_id,
                "ask_question_retry",
                qid=qid,
                reason="vague_or_historical_dup",
                before=question[:80],
            )
            retry_user = (
                user
                + "\n\n【硬性重出】上一稿无效：与历史问法重复，或是空泛的「如何编排/设计多 Agent」。"
                "必须换成具体落地角度（失败重试、评测指标、权限、RAG 幻觉等），禁止再问编排空话。"
            )
            try:
                raw2 = self.llm.chat_json(ASK_QUESTION_SYSTEM, retry_user)
                if isinstance(raw2, dict):
                    q2 = str(raw2.get("question") or "").strip()
                    if (
                        q2
                        and not _looks_like_vague_orchestration(q2)
                        and not _conflicts_historical_question(q2, asked_blobs)
                    ):
                        question = q2
                        raw = raw2
            except Exception:  # noqa: BLE001
                pass
        pq["pending_asked_text"] = question
        pq["pending_reference_answer"] = str(raw.get("reference_answer") or "").strip()
        return question

    def _resume_cite_whitelist(self, state: InterviewState) -> str:
        profile = state.profile or {}
        skills = [str(s) for s in (profile.get("skills") or []) if str(s).strip()][:30]
        projects = []
        for p in profile.get("projects") or []:
            name = str(p.get("name") or "").strip()
            tech = [str(x) for x in (p.get("tech_stack") or []) if str(x).strip()]
            if name:
                projects.append(f"{name}（{'、'.join(tech[:8]) or '技术未标注'}）")
        lines = [
            "项目：" + ("；".join(projects) if projects else "（无）"),
            "技能：" + ("、".join(skills) if skills else "（无）"),
            "目标岗位：" + (state.target_role or "（未选）") + " —— 岗位考点≠简历内容",
        ]
        return "\n".join(lines)

    def _sanitize_resume_claim(self, question: str, state: InterviewState) -> str:
        """挡住「简历提到了X」但 X 根本不在简历里的幻觉措辞。"""
        import re

        text = (question or "").strip()
        if not text:
            return text
        claim = re.search(
            r"((?:我看到)?你(?:在)?简历(?:中|上|里)?(?:曾经)?(?:提到|写到|写了|有着?)(?:了|过)?"
            r"(?P<obj>[^，。；？?\n]{1,24}))",
            text,
        )
        if not claim:
            return text
        obj = (claim.group("obj") or "").strip(" ：:的 ")
        if not obj:
            return text
        blob = (
            (state.resume_raw or "")
            + json.dumps(state.profile or {}, ensure_ascii=False)
        ).lower()
        # 对象里抽出实质词：任一命中简历则视为可引用
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9+.\-]{1,}", obj)
        filler = {"相关", "项目", "技术", "熟悉", "开发", "场景", "经验", "内容", "方面", "使用", "采用"}
        keys = [t for t in tokens if t not in filler]
        if keys and any(t.lower() in blob or t in blob for t in keys):
            return text
        rest = text[claim.end() :].lstrip("，,：: 、")
        from app.services.session_guard_log import log_guard

        log_guard(
            state.session_id,
            "resume_claim_sanitized",
            claim_obj=obj[:40],
            before=text[:100],
        )
        if rest:
            if state.target_role and not rest.startswith("结合目标岗位"):
                return f"结合目标岗位「{state.target_role}」，{rest}"
            return rest
        if state.target_role:
            return f"结合目标岗位「{state.target_role}」，请谈谈本题相关技术点。"
        return text

    def _performance_block(self, state: InterviewState) -> str:
        """按引擎规则拼装候选人近期表现：已答评分均分 + 是否明确表示过不会。"""
        scores: list[float] = []
        weak_topics: list[str] = []
        for i in range(state.cursor):
            q = state.plan[i]
            pq = state.per_question.get(q["qid"], {})
            if pq.get("score") is not None:
                scores.append(float(pq["score"]))
            if any(
                kw in a for a in pq.get("answers", []) for kw in WEAK_KEYWORDS
            ):
                weak_topics.append(q["topic"])
        if not scores and not weak_topics:
            return "（第一题，暂无表现数据）"
        lines = []
        if weak_topics:
            lines.append(
                f"候选人对以下主题明确表示不会或没接触过：{'、'.join(weak_topics)}"
            )
        if scores:
            avg = sum(scores) / len(scores)
            if avg < 4:
                lines.append(
                    f"近期回答均分 {avg:.1f}/10，基础薄弱：请把本问题问得基础一些，从概念切入，用引导式问法，必要时先给出提示再继续。"
                )
            elif avg < 7:
                lines.append(
                    f"近期回答均分 {avg:.1f}/10，中等水平：按正常难度提问，回答不完整时可适当引导。"
                )
            else:
                lines.append(
                    f"近期回答均分 {avg:.1f}/10，表现优秀：保持提问深度，可往复杂场景深挖。"
                )
        return "\n".join(lines)

    def _ctx_block(self, state: InterviewState) -> str:
        profile = json.dumps(state.profile, ensure_ascii=False)
        target = ""
        if state.target_role or state.target_company:
            parts = [p for p in (state.target_role, state.target_company) if p]
            target = (
                f"\n\n【目标岗位/目标企业——本场最高优先级】\n"
                f"{'，'.join(parts)}\n"
                "硬性要求：整场出题、追问、八股必须服务该岗位能力模型；"
                "简历项目只是素材，禁止被简历原技术栈牵着走"
                "（例：目标搜广推时，不要把校园二手项目问成 Redis 缓存专项）。"
            )
        focus = ""
        if state.practice_focus:
            focus = (
                "\n\n【本场练习焦点——仅本场有效，不是跨场记忆】\n"
                + state.practice_focus
                + "\n请在规划与提问中优先覆盖上述焦点，但仍保持一场完整、独立的模拟面试。"
            )
        review = ""
        if state.review_mode:
            review = (
                "\n\n【复习模式】\n"
                "请优先复盘候选人历史短板与薄弱主题；可换角度深挖，但不要机械复读原题。"
            )
        avoid = ""
        if state.avoid_topics:
            sample = "；".join(str(t)[:80] for t in state.avoid_topics[:40])
            avoid = (
                "\n\n【历史问题去重——禁止换句重复，允许换角度再考】\n"
                + sample
                + "\n硬性：不得把历史题换个说法再问一遍；"
                "同一知识点以后仍可问，但必须是全新角度（例：上次问 MindBridge×MCP 封装，"
                "这次可问 MCP 失败重试/权限，或改问 RAG/规划，不要再复述「封装 Excel/邮件工具」那一套）。"
                "缓存穿透与缓存击穿算不同角度。"
            )
        resume_note = (
            "\n\n【简历使用方式】\n"
            "简历用于核实经历与改写题面；若与目标岗位冲突，以目标岗位为准，"
            "把项目经历改写成该岗位视角的考察题。"
        )
        return (
            "【候选人简历原文】\n"
            + state.resume_raw[:4000]
            + "\n\n【候选人画像】\n"
            + profile[:2000]
            + "\n\n【自我介绍】\n"
            + (state.intro_text or "（候选人尚未自我介绍）")
            + target
            + resume_note
            + focus
            + review
            + avoid
        )

    def _router_user(self, state: InterviewState, depth: dict | None = None) -> str:
        block = self._ctx_block(state)
        capacity = getattr(self, "_askable_capacity", None) or {}
        if capacity:
            askable = capacity.get("askable") or []
            lines = [
                f"- {x.get('name')}（{x.get('kind', 'project')}，可问约{x.get('slots')}题，岗位相关度{x.get('role_score', 0):.1f}）"
                for x in askable
            ]
            block += (
                "\n\n【岗位可问容量（引擎评估，分题依据）】\n"
                + ("\n".join(lines) if lines else "- 无足够岗位相关项目/实习可深挖 → 八股为主")
                + f"\n建议项目题：{capacity.get('max_project_questions', 0)} 道（先列项目，其余八股补）"
            )
        if state.target_company:
            block += (
                f"\n\n【目标企业】{state.target_company}\n"
                "召回素材优先该企业原题 + 无企业标签通用题；"
                "禁止把其他公司的面经当作本场企业原题注入。"
            )
        return block + "\n\n请根据【目标岗位优先 + 可问容量】决定项目/八股数量（项目先列，八股补充）。"

    def _planner_user(self, state: InterviewState) -> str:
        user = self._ctx_block(state)
        # 多路检索素材 + 拷打链注入规划官
        if state.retrieved_material:
            user += (
                "\n\n【真实面试题多路召回（参考素材，已分区）】\n"
                + state.retrieved_material
            )
        if state.project_chains:
            from app.services.project_cross import chain_block_for

            user += (
                "\n\n【项目拷打链（已综合岗位+场景现编；规划项目题时对齐问点）】\n"
                + "\n".join(chain_block_for([pc], pc["project"]) for pc in state.project_chains)
            )
        from app.services.job_roles import resume_project_names

        names = resume_project_names(state.profile or {}, state.target_role or "", limit=3)
        if names and int(getattr(self, "_plan_project_n", 0) or 0) > 1:
            quotas = _project_quotas(int(self._plan_project_n), len(names))
            dist = "、".join(f"「{n}」{q}题" for n, q in zip(names, quotas))
            user += (
                f"\n\n【项目题分配——硬性】共 {self._plan_project_n} 道项目题，"
                f"必须在以下简历项目间均衡分配：{dist}。"
                "最相关目标岗位的项目优先排前；"
                "禁止连续多题只问同一个项目；"
                "与目标岗位无关的纯原栈深挖（例：面 Agent 岗却主问 Redis 缓存）必须少问或不问。"
            )
        return (
            user
            + "\n\n请生成面试问题计划。"
            "岗位定考察能力，场景真题定真人怎么挖项目；综合两路素材改写，勿照搬原题。"
        )

    def _question_context(self, state: InterviewState, qid: str) -> str:
        """追问官上下文：分区标注 + 本题对话 + 已覆盖考点防重复。"""
        q = state.plan[state.cursor]
        pq = state.per_question.get(qid, {})
        turns = pq.get("turns") or []
        lines = [
            "以下信息严格分区：简历≠当场作答；题干≠候选人回答。",
            self._ctx_block(state),
            f"【B. 本题题签】\n主题：{q['topic']}\n关键问点：{q['text']}",
        ]
        if q.get("rubric"):
            lines.append(f"【C. rubric】\n{q['rubric']}")
        asked_qs = [str(t.get("question") or "").strip() for t in turns if t.get("question")]
        pending = str(pq.get("pending_asked_text") or "").strip()
        if not pending and state.history:
            for m in reversed(state.history):
                if m["role"] == "interviewer":
                    pending = m["text"]
                    break
        if pending:
            asked_qs = asked_qs + [pending]
        if asked_qs:
            lines.append("【已问过的问题——禁止换句重复同一考点】\n- " + "\n- ".join(asked_qs))
        covered = [str(t.get("answer") or "").strip()[:120] for t in turns if t.get("answer")]
        if covered:
            lines.append(
                "【候选人已答内容摘要——已覆盖考点勿再追问】\n- " + "\n- ".join(covered)
            )
        lines.append("【D. 本题对话】")
        # 拷打链：项目题注入（追问官可按 trigger 顺着深挖）
        if q["type"] == "project" and state.project_chains:
            from app.services.project_cross import chain_block_for

            lines.append(
                "【本项目拷打链——候选人答到触发点时可顺着追问（触发：追问）】\n"
                + "\n".join(chain_block_for([pc], pc["project"]) for pc in state.project_chains)
            )
        started = False
        for m in state.history:
            if m["role"] == "interviewer" and (
                m["text"] == q["text"]
                or q["topic"] in m["text"]
                or (asked_qs and m["text"] == asked_qs[0])
            ):
                started = True
            if started:
                lines.append(
                    f"{'面试官' if m['role'] == 'interviewer' else '候选人'}：{m['text']}"
                )
        if not started:
            for a in pq.get("answers") or []:
                lines.append(f"候选人：{a}")
        lines.append(
            "【追问硬约束】只能转向尚未覆盖的关键问点或更深边界；"
            "若继续问只会重复（如反复问缓存穿透）→ needs_follow_up=false"
        )
        return "\n".join(lines)

    def _score_context(
        self, state: InterviewState, qid: str, answer_only: str | None = None
    ) -> str:
        """评分官专用：A/B/C/D 分区，strengths 只能来自 D。默认只评本轮作答。"""
        q = state.plan[state.cursor]
        pq = state.per_question.get(qid, {})
        asked = str(pq.get("pending_asked_text") or "").strip() or q.get("text") or q["topic"]
        lines = [
            "以下信息严格分区。评分时只能把【D. 候选人当场作答】当作证据；"
            "【A】【B】【C】不是候选人说过的话，禁止写入 strengths。",
            "",
            "【A. 简历与画像——仅背景，禁止写成 strengths】",
            state.resume_raw[:2000],
            json.dumps(state.profile, ensure_ascii=False)[:1000],
            "",
            "【B. 本轮题干——面试官问的内容，不是候选人回答】",
            f"主题：{q['topic']}",
            f"问题：{asked}",
            "",
            "【C. rubric——评分尺子，不是候选人回答】",
            q.get("rubric") or "（无）",
            "",
            "【D. 候选人当场作答——strengths/weaknesses 唯一允许引用的来源】",
        ]
        if answer_only is not None:
            lines.append(answer_only or "（无作答）")
        else:
            answers = pq.get("answers") or []
            if not answers:
                lines.append("（无作答）")
            else:
                for i, a in enumerate(answers):
                    lines.append(f"回答{i + 1}：{a}")
        return "\n".join(lines)

    def _past_summaries(self, state: InterviewState) -> str:
        parts = []
        for i in range(state.cursor):
            q = state.plan[i]
            pq = state.per_question.get(q["qid"], {})
            parts.append(f"- 第{i + 1}题：{q['text']} → {pq.get('summary', '')}")
        return "\n".join(parts)

    def _make_summary(self, state: InterviewState, qid: str, pq: dict) -> str:
        q = state.plan[state.cursor]
        best = pq["answers"][-1][:150] if pq["answers"] else ""
        return (
            f"主题：{q['topic']} | 回答要点：{best} | 评分：{pq['score']}/10 "
            f"| 优点：{'；'.join(pq['strengths'][:2])} | 不足：{'；'.join(pq['weaknesses'][:2])} | 追问次数：{pq['followups_so_far']}"
        )

    def _report_user(self, state: InterviewState) -> str:
        from app.services.code_judger import get_problem

        qa_lines = [
            "【说明】A=简历背景；B=每轮题干；C=该轮作答（唯一证据）；D=引擎预评分。"
            "主问与每一次追问已拆成独立轮次；报告 per_question 必须按轮次拆条，禁止把多轮合并。"
            "不得把 A/B 写成亮点；C 为空答/跳过则该轮 strengths 必须为 [] 且低分。"
        ]
        for q in state.plan:
            pq = state.per_question.get(q["qid"], {})
            turns = pq.get("turns") or []
            original = str(q.get("original_company") or "").strip()
            if not turns:
                answers = pq.get("answers") or []
                qa_lines.append(f"\n===== 题目：{q['topic']}（未拆轮，整题） =====")
                if original:
                    qa_lines.append(f"【企业原题】{original}（该题直接采用 {original} 真实面试题，original_company 字段透传）")
                qa_lines.append(f"【B. 题干】{q['text']}")
                qa_lines.append("【C. 候选人当场作答】")
                if not answers:
                    qa_lines.append("  （无作答）")
                else:
                    for i, a in enumerate(answers):
                        qa_lines.append(f"  回答{i + 1}：{a}")
                qa_lines.append(
                    f"【D. 引擎预评分】{pq.get('score')}/10；"
                    f"预评优点：{pq.get('strengths')}；不足：{pq.get('weaknesses')}"
                )
                if is_non_answer(answers):
                    qa_lines.append("【硬约束】本题为跳过/敷衍/注入作答 → score=1，strengths=[]")
            else:
                for ti, t in enumerate(turns):
                    label = q["topic"] if ti == 0 else f"{q['topic']} · 追问{ti}"
                    qa_lines.append(f"\n===== 轮次：{label} =====")
                    qa_lines.append(f"【B. 本轮问题】{t.get('question') or q['text']}")
                    if q.get("rubric") and ti == 0:
                        qa_lines.append(f"【B. rubric】{q['rubric']}")
                    ans = t.get("answer") or ""
                    qa_lines.append(f"【C. 本轮作答】{ans or '（无作答）'}")
                    if t.get("reference_answer"):
                        qa_lines.append(
                            "【已预置参考答案——优先写入 reference_answer】\n"
                            + str(t["reference_answer"])[:1500]
                        )
                    qa_lines.append(
                        f"【D. 引擎本轮预评分】{t.get('score')}/10；"
                        f"优点：{t.get('strengths')}；不足：{t.get('weaknesses')}"
                    )
                    if is_non_answer([ans]):
                        qa_lines.append("【硬约束】本轮为跳过/敷衍 → score=1，strengths=[]")
            if q["type"] == "coding" and q.get("slug"):
                problem = get_problem(q["slug"])
                if problem and problem.get("reference"):
                    qa_lines.append(
                        "【参考解法——仅供写 reference_answer，禁止写入 strengths】\n"
                        + problem["reference"][:1500]
                    )
            elif q["type"] != "coding":
                # 非算法题：从知识库原文块取参考答案素材（终评官 reference_answer 用）
                from app.services.knowledge_retrieval import format_answer_material

                material = format_answer_material(f"{q['topic']} {q['text']}")
                if material:
                    qa_lines.append(
                        "【参考答案素材（知识库原文，供 reference_answer 参考，不得写入 strengths）】\n"
                        + material
                    )
        return (
            "【A. 简历与画像——仅背景】\n"
            + self._ctx_block(state)
            + "\n\n【B/C/D. 各轮分区材料】\n"
            + "\n".join(qa_lines)
        )

    def _expand_turns_for_report(self, state: InterviewState) -> list[dict]:
        """引擎权威拆条：主问/追问各一条。"""
        items: list[dict] = []
        for q in state.plan:
            pq = state.per_question.get(q["qid"], {})
            turns = pq.get("turns") or []
            original = str(q.get("original_company") or "").strip()
            if not turns:
                answers = [str(a) for a in (pq.get("answers") or [])]
                items.append(
                    {
                        "topic": q["topic"],
                        "question": q.get("text") or q["topic"],
                        "my_answers": answers if answers else ["（未作答）"],
                        "is_followup": False,
                        "score": pq.get("score") if pq.get("score") is not None else 1,
                        "strengths": list(pq.get("strengths") or []),
                        "weaknesses": list(pq.get("weaknesses") or []),
                        "feedback": "",
                        "reference_answer": "",
                        "original_company": original,
                        "_answers_raw": answers,
                    }
                )
                continue
            for ti, t in enumerate(turns):
                ans = str(t.get("answer") or "").strip()
                items.append(
                    {
                        "topic": q["topic"] if ti == 0 else f"{q['topic']} · 追问{ti}",
                        "question": str(t.get("question") or "").strip()
                        or (q.get("text") if ti == 0 else f"{q['topic']}追问"),
                        "my_answers": [ans] if ans else ["（未作答）"],
                        "is_followup": bool(t.get("is_followup")) or ti > 0,
                        "score": t.get("score") if t.get("score") is not None else 1,
                        "strengths": list(t.get("strengths") or []),
                        "weaknesses": list(t.get("weaknesses") or []),
                        "feedback": "",
                        "reference_answer": str(t.get("reference_answer") or ""),
                        "original_company": original if ti == 0 else "",
                        "_answers_raw": [ans] if ans else [],
                    }
                )
        return items

    def _sanitize_report(self, state: InterviewState, report: dict) -> dict:
        """终评硬校验：按 turns 拆条，压掉空答高分与无作答依据的亮点。"""
        if not isinstance(report, dict):
            return report

        llm_per = report.get("per_question")
        if not isinstance(llm_per, list):
            llm_per = []

        expanded = self._expand_turns_for_report(state)
        all_answers: list[str] = []
        out: list[dict] = []

        for i, item in enumerate(expanded):
            answers = [str(a) for a in (item.pop("_answers_raw", None) or [])]
            all_answers.extend(answers)
            if i < len(llm_per) and isinstance(llm_per[i], dict):
                llm_item = llm_per[i]
                if not item.get("feedback"):
                    item["feedback"] = str(llm_item.get("feedback") or "").strip()
                if not item.get("reference_answer"):
                    item["reference_answer"] = str(
                        llm_item.get("reference_answer") or ""
                    ).strip()
                if not item.get("strengths") and llm_item.get("strengths"):
                    item["strengths"] = llm_item.get("strengths")
                if not item.get("weaknesses") and llm_item.get("weaknesses"):
                    item["weaknesses"] = llm_item.get("weaknesses")
                if llm_item.get("score") is not None and item.get("score") is None:
                    item["score"] = llm_item.get("score")
                if not item.get("original_company"):
                    from app.services.job_roles import company_display_name

                    oc = str(llm_item.get("original_company") or "").strip()
                    if oc:
                        item["original_company"] = company_display_name(oc) or oc

            sc, strengths, weaknesses = sanitize_score_fields(
                answers,
                item.get("score", 1),
                item.get("strengths"),
                item.get("weaknesses"),
            )
            if is_non_answer(answers):
                sc = min(float(sc), NON_ANSWER_MAX_SCORE)
                strengths = []
                raw = "；".join(answers) if answers else "未作答"
                item["feedback"] = (
                    f"本轮未有效作答（作答：{raw}），未展现对题干要点的理解，故给予低分。"
                )
                if not weaknesses:
                    weaknesses = ["未有效回答本题要点"]
            item["score"] = sc
            item["strengths"] = strengths
            item["weaknesses"] = weaknesses
            if answers:
                item["my_answers"] = answers
            out.append(item)

        report["per_question"] = out
        report["strengths"] = filter_strengths(report.get("strengths"), all_answers, None)
        report["weaknesses"] = [
            str(x).strip() for x in (report.get("weaknesses") or []) if str(x).strip()
        ]
        report["suggestions"] = [
            str(x).strip() for x in (report.get("suggestions") or []) if str(x).strip()
        ]
        dims = report.get("dimension_scores")
        if not isinstance(dims, dict) or not dims:
            report["dimension_scores"] = {
                "技术深度": 1,
                "项目经验": 1,
                "沟通表达": 1,
                "综合素质": 1,
            }
        if state.plan and all(
            is_non_answer(state.per_question.get(q["qid"], {}).get("answers"))
            for q in state.plan
        ):
            capped = {}
            for k, v in (report.get("dimension_scores") or {}).items():
                try:
                    capped[k] = min(float(v), NON_ANSWER_MAX_SCORE)
                except (TypeError, ValueError):
                    capped[k] = 1.0
            report["dimension_scores"] = capped
        report.pop("per_question_calibrated", None)
        if not str(report.get("summary") or "").strip():
            report["summary"] = "本场有效作答有限，整体表现不足以支撑高分评价。"
        return report
