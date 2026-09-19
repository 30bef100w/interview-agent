"""提示词上下文：简历白名单、表现块、规划官/追问官/评分官输入。"""
from __future__ import annotations

import json

from app.schemas.interview import InterviewState

from .constants import WEAK_KEYWORDS
from .guards import _project_quotas


class ContextMixin:
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
        if state.practice_focus or state.job_description:
            focus = (
                "\n\n【用户偏好（JD/练习焦点）】\n"
                "候选人可能填写了岗位 JD 或练习焦点；系统已在题库召回阶段做关键词加权，"
                "规划时仍以目标岗位+简历+题库硬约束为准，勿只围着偏好词出题、勿把 JD 当 few-shot。"
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
