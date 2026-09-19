"""题单组装：配额、规划官、项目均衡、去重补齐、兜底。"""
from __future__ import annotations

import logging
import re
import time

from app.prompts.interview import PLANNER_SYSTEM, ROUTER_SYSTEM
from app.schemas.interview import InterviewState, PerQuestion
from app.services.question_bank import pick_coding_question

from .constants import BA_GU_CLAMP, PROJECT_CLAMP, _DIVERSE_PROJECT_ANGLES
from .guards import (
    _clamp,
    _conflicts_bagu_knowledge,
    _conflicts_historical_question,
    _conflicts_plan_sibling,
    _is_similar_question,
    _looks_like_vague_orchestration,
    _project_quotas,
    _question_mentions_project,
)

logger = logging.getLogger(__name__)


class PlanningMixin:
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
        from app.observability.node_trace import trace_node

        with trace_node(
            "build_plan",
            session_id=state.session_id,
            project_n=project_n,
            ba_gu_n=ba_gu_n,
            hr_n=hr_n,
        ):
            self._build_plan_body(state, mode, project_n, ba_gu_n, hr_n)

    def _build_plan_body(
        self, state: InterviewState, mode: str, project_n: int, ba_gu_n: int, hr_n: int
    ) -> None:
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
