"""面试状态机引擎：LLM 只生成语言，控制决策归引擎。

无状态服务模式：引擎方法都是 (state, input) -> (new_state, output) 纯推进，
DB 持久化由 API 层负责。llm 通过构造注入（LlmPort），单测传 fake，不依赖 FastAPI。
"""
from __future__ import annotations

import logging
import time

from app.prompts.interview import OPENING_SYSTEM
from app.schemas.interview import InterviewState
from app.services.llm.client import LlmPort

from .bagu import BaguMixin
from .context import ContextMixin
from .planning import PlanningMixin
from .report import ReportMixin
from .retrieval import RetrievalMixin
from .runtime import RuntimeMixin

logger = logging.getLogger(__name__)


class InterviewEngine(
    RetrievalMixin,
    PlanningMixin,
    BaguMixin,
    RuntimeMixin,
    ContextMixin,
    ReportMixin,
):
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
        job_description: str = "",
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
            job_description=job_description.strip()[:4000],
            practice_focus=practice_focus.strip()[:500],
            skip_coding=bool(skip_coding),
            review_mode=bool(review_mode),
            avoid_topics=list(avoid_topics or [])[:80],
        )
        from app.services.recall_boost import build_recall_boost_terms, recall_boost_context

        boost_terms = build_recall_boost_terms(
            state.job_description, state.practice_focus
        )
        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        from app.services.create_timing_log import step as trace_step

        t_open = time.perf_counter()
        try:
            opening = self.llm.chat_text(OPENING_SYSTEM, self._ctx_block(state))
        except Exception as exc:  # noqa: BLE001
            from app.services.session_guard_log import log_guard

            log_guard(session_id, "opening_llm_failed", reason=type(exc).__name__)
            opening = (
                "你好，欢迎参加本次模拟面试。"
                "请先结合简历做一个简短的自我介绍，重点讲技术背景和最想展开的项目。"
            )
        timings["opening_llm_s"] = time.perf_counter() - t_open
        trace_step(session_id, "opening_llm", duration_s=round(timings["opening_llm_s"], 2))
        state.history.append({"role": "interviewer", "text": opening})

        with recall_boost_context(boost_terms):
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
                recall_boost_n=len(boost_terms),
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
