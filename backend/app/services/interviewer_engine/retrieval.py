"""规划前置：A/B 路召回、LLM 滤岗、可问容量。"""
from __future__ import annotations

import json
import time

from app.schemas.interview import InterviewState

from .guards import _is_suspect_pure_backend_project_blob


class RetrievalMixin:
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
        """多路召回（存 retrieved_material 给规划官作参考）+ 生成项目拷打链（存 project_chains）。

        A 路：岗+企学出题风格（技术点仅辅助权重，不传场景）
        B 路：技术点+场景学问法（LLM 从简历闭集勾选；岗位仍硬卡）
        注入规划官的是参考题面，要求改写交叉，不是从池子里勾原题。
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

        from app.services.b_lane_query import collect_resume_scenes, collect_resume_skills

        skills = [str(s) for s in (profile.get("skills") or [])]
        retrieve_skills = skills[:6] if roles else skills
        can_b_lane = bool(collect_resume_scenes(profile) or collect_resume_skills(profile))
        role_limit, scene_limit = kr.planner_material_limits(state.total_rounds)
        if not can_b_lane:
            role_limit = role_limit + scene_limit
            scene_limit = 0
        role_fetch = role_limit + 4
        scene_fetch = (scene_limit + 4) if scene_limit else 0
        role_pool = max(32, role_limit * 2)
        scene_pool = max(32, scene_limit * 2)
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
                    top_n=role_limit,
                    pool_size=role_pool,
                    min_score=20,
                )
                untagged_role = kr.retrieve(
                    roles=roles,
                    company=None,
                    skills=retrieve_skills,
                    scenes=None,
                    asked_norms=asked_norms,
                    top_n=role_limit,
                    pool_size=role_pool,
                    min_score=20,
                )
                role_hits = kr.merge_company_and_untagged(
                    company_role,
                    untagged_role,
                    company=company_id,
                    limit=role_fetch,
                )
            else:
                role_hits = kr.retrieve(
                    roles=roles,
                    company=None,
                    skills=retrieve_skills,
                    scenes=None,  # 场景走 B 路，避免和岗位硬门槛搅在一起
                    asked_norms=asked_norms,
                    top_n=role_fetch,
                    pool_size=role_pool,
                    min_score=20,
                )
            if len(role_hits) < max(6, role_limit // 2):
                more_plain = kr.search_questions(
                    roles=roles,
                    company=None,
                    asked_norms=asked_norms,
                    top_n=role_fetch,
                    min_score=10,
                )
                if company_id:
                    more_co = kr.search_questions(
                        roles=roles,
                        company=company_id,
                        asked_norms=asked_norms,
                        top_n=role_fetch,
                        min_score=10,
                    )
                    role_hits = kr.merge_company_and_untagged(
                        more_co,
                        more_plain,
                        company=company_id,
                        limit=role_fetch,
                        extra=role_hits,
                    )
                else:
                    role_hits = kr.merge_hits(role_hits, more_plain, limit=role_fetch)
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
                scenes=collect_resume_scenes(profile) or None,
                asked_norms=asked_norms,
                top_n=role_fetch,
                pool_size=role_pool,
                min_score=30,
            )

        scene_roles = roles if roles else None
        # —— B 路：技术点 + 场景（岗位硬卡；LLM 从简历闭集勾选）——
        scene_hits: list[dict] = []
        b_scenes, b_skills = self._select_b_lane_query(
            state, roles, timings=timings
        )
        b_skill_arg = b_skills or None
        b_scene_arg = b_scenes or None
        if b_scenes or b_skills:
            if company_id:
                company_scene = kr.retrieve(
                    roles=scene_roles,
                    company=company_id,
                    skills=b_skill_arg,
                    scenes=b_scene_arg,
                    category="project",
                    asked_norms=asked_norms,
                    top_n=scene_limit,
                    pool_size=scene_pool,
                    min_score=28,
                    lane="b",
                )
                untagged_scene = kr.retrieve(
                    roles=scene_roles,
                    company=None,
                    skills=b_skill_arg,
                    scenes=b_scene_arg,
                    category="project",
                    asked_norms=asked_norms,
                    top_n=scene_limit,
                    pool_size=scene_pool,
                    min_score=28,
                    lane="b",
                )
                scene_hits = kr.merge_company_and_untagged(
                    company_scene,
                    untagged_scene,
                    company=company_id,
                    limit=scene_fetch,
                )
            else:
                scene_hits = kr.retrieve(
                    roles=scene_roles,
                    company=None,
                    skills=b_skill_arg,
                    scenes=b_scene_arg,
                    category="project",
                    asked_norms=asked_norms,
                    top_n=scene_fetch,
                    pool_size=scene_pool,
                    min_score=28,
                    lane="b",
                )
            if len(scene_hits) < max(4, scene_limit // 3):
                more = kr.search_questions(
                    roles=scene_roles,
                    skills=b_skill_arg,
                    scenes=b_scene_arg,
                    category="project",
                    asked_norms=asked_norms,
                    top_n=scene_fetch,
                    min_score=20,
                    lane="b",
                )
                if company_id:
                    more_co = kr.search_questions(
                        roles=scene_roles,
                        company=company_id,
                        skills=b_skill_arg,
                        scenes=b_scene_arg,
                        category="project",
                        asked_norms=asked_norms,
                        top_n=scene_limit,
                        min_score=15,
                        lane="b",
                    )
                    scene_hits = kr.merge_company_and_untagged(
                        more_co,
                        more,
                        company=company_id,
                        limit=scene_fetch,
                        extra=scene_hits,
                    )
                else:
                    scene_hits = kr.merge_hits(scene_hits, more, limit=scene_fetch)
            # 再补一轮不限 category，防止场景项目题过少
            if len(scene_hits) < max(4, scene_limit // 3):
                more2 = kr.search_questions(
                    roles=scene_roles,
                    skills=b_skill_arg,
                    scenes=b_scene_arg,
                    asked_norms=asked_norms,
                    top_n=scene_fetch,
                    min_score=24,
                    lane="b",
                )
                scene_hits = kr.merge_hits(scene_hits, more2, limit=scene_fetch)
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
            timings["b_lane_skills_n"] = float(len(b_skills))
            timings["b_lane_scenes_n"] = float(len(b_scenes))

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
            role_limit=role_limit,
            scene_limit=scene_limit,
        )

        # 拷打链：与题单分开；每简历项目各生成一条完整链（失败跳过单项目）
        from app.services.create_timing_log import step as trace_step

        trace_step(state.session_id, "project_chains", status="started")
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
        trace_step(
            state.session_id,
            "project_chains",
            duration_s=round(timings.get("project_chains_s", 0), 2) if timings else 0,
            chains=len(state.project_chains or []),
        )

    def _select_b_lane_query(
        self,
        state: InterviewState,
        roles: list[str],
        timings: dict[str, float] | None = None,
    ) -> tuple[list[str], list[str]]:
        """本场 B 路 scenes/skills：LLM 从简历闭集勾选，失败则规则兜底。"""
        from app.services.b_lane_query import (
            B_LANE_QUERY_SYSTEM,
            build_b_lane_user,
            clip_b_lane_query,
            collect_resume_scenes,
            collect_resume_skills,
            fallback_b_lane_query,
        )
        from app.services.session_guard_log import log_guard

        profile = state.profile or {}
        if not collect_resume_scenes(profile) and not collect_resume_skills(profile):
            return [], []

        t0 = time.perf_counter()
        source = "fallback"
        try:
            raw = self.llm.chat_json(
                B_LANE_QUERY_SYSTEM,
                build_b_lane_user(profile, state.target_role, roles),
                max_retries=1,
            )
            scenes, skills = clip_b_lane_query(raw, profile=profile)
            if scenes or skills:
                source = "llm"
            else:
                scenes, skills = fallback_b_lane_query(profile)
                log_guard(
                    state.session_id,
                    "b_lane_query_empty_fallback",
                    role_n=len(roles),
                )
        except Exception as exc:  # noqa: BLE001
            scenes, skills = fallback_b_lane_query(profile)
            log_guard(
                state.session_id,
                "b_lane_query_failed",
                reason=type(exc).__name__,
            )
        if timings is not None:
            timings["b_lane_query_s"] = time.perf_counter() - t0
            timings["b_lane_query_source"] = 1.0 if source == "llm" else 0.0
        from app.services.create_timing_log import step as trace_step

        trace_step(
            state.session_id,
            "b_lane_query",
            duration_s=round(time.perf_counter() - t0, 2),
            source=source,
            scenes=len(scenes),
            skills=len(skills),
        )
        return scenes, skills

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
