"""面试推进：自我介绍、作答、追问、算法题、出题。"""
from __future__ import annotations

from app.prompts.interview import (
    ASK_QUESTION_STREAM_SYSTEM,
    ASK_QUESTION_SYSTEM,
    FOLLOW_UP_SYSTEM,
    INTERVIEWER_SYSTEM,
    REFERENCE_ANSWER_SYSTEM,
    SCORE_SYSTEM,
)
from app.schemas.interview import InterviewState

from .constants import (
    ANSWER_TRUNCATE,
    MAX_FOLLOW_UPS_PER_QUESTION,
    NON_ANSWER_MAX_SCORE,
    SUMMARIZING_TEXT,
)
from .guards import (
    _conflicts_historical_question,
    _is_repeat_followup,
    _looks_like_vague_orchestration,
    is_non_answer,
    looks_like_rubric,
    sanitize_score_fields,
)


class RuntimeMixin:
    def handle_intro(self, state: InterviewState, answer: str):
        from app.observability.node_trace import trace_node

        if not state.plan:
            raise ValueError("面试尚未规划")
        state.intro_text = answer
        state.history.append({"role": "candidate", "text": answer})
        state.stage = "ASKING"

        with trace_node("handle_intro", session_id=state.session_id):
            with trace_node("ask_question", session_id=state.session_id):
                message = self._ask_question(state)
        state.history.append({"role": "interviewer", "text": message})
        return state, message

    def handle_answer(self, state: InterviewState, answer: str):
        from app.observability.node_trace import trace_node

        if not state.plan:
            raise ValueError("面试尚未规划")
        qid = f"q{state.cursor + 1}"
        q = state.plan[state.cursor]
        pq = state.per_question[qid]
        clipped = answer[:ANSWER_TRUNCATE]
        pq["answers"].append(clipped)
        state.history.append({"role": "candidate", "text": answer})
        state.rounds_used += 1

        score_ctx = self._score_context(state, qid, answer_only=clipped)
        follow_ctx = self._question_context(state, qid)
        with trace_node("follow_up_and_score", session_id=state.session_id):
            judge, score = self.llm.chat_json_many(
                [
                    (FOLLOW_UP_SYSTEM, follow_ctx + "\n\n【候选人最新回答】\n" + answer),
                    (SCORE_SYSTEM, score_ctx),
                ]
            )
        with trace_node("score_sanitize", session_id=state.session_id):
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
            pq["pending_reference_answer"] = self._usable_reference(
                judge.get("follow_up_reference_answer"), q, fq
            )
            self._stream_interviewer_message(fq)
            state.history.append({"role": "interviewer", "text": fq})
            return state, fq

        with trace_node("question_summary", session_id=state.session_id):
            pq["summary"] = self._make_summary(state, qid, pq)
        state.cursor += 1
        if state.cursor < len(state.plan):
            with trace_node("ask_question", session_id=state.session_id):
                message = self._ask_question(state)
            state.history.append({"role": "interviewer", "text": message})
            return state, message

        # 全部主问题完成 → 进入汇总（不再反问）
        state.stage = "SUMMARIZING"
        self._stream_interviewer_message(SUMMARIZING_TEXT)
        state.history.append({"role": "interviewer", "text": SUMMARIZING_TEXT})
        return state, SUMMARIZING_TEXT

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

    def _stream_interviewer_message(self, text: str) -> None:
        if not text:
            return
        emit = getattr(self.llm, "emit_tokens", None)
        if callable(emit):
            emit(text)

    def _usable_reference(self, candidate: object, q: dict, asked: str) -> str:
        text = str(candidate or "").strip()
        if text and not looks_like_rubric(text) and len(text) >= 40:
            return text
        return self._compose_reference_answer(q, asked)

    def _compose_reference_answer(self, q: dict, asked: str) -> str:
        """生成候选人可见的完整口头参考答，绝不回落成 rubric 档位。"""
        bank = str(q.get("bank_answer") or "").strip()
        if bank and not looks_like_rubric(bank) and len(bank) >= 40:
            return bank
        asked = (asked or "").strip() or str(q.get("text") or q.get("topic") or "").strip()
        user = (
            f"面试官实际问出的问题：{asked}\n"
            f"主题：{q.get('topic') or ''}\n"
            f"关键问点：{q.get('text') or ''}\n"
            f"覆盖要点（只作提纲，禁止照抄档位原文）：{q.get('rubric') or '无'}\n"
        )
        try:
            raw = self.llm.chat_json(REFERENCE_ANSWER_SYSTEM, user)
            ans = str((raw or {}).get("reference_answer") or "").strip()
            if ans and not looks_like_rubric(ans) and len(ans) >= 80:
                return ans
        except Exception:
            logger.exception("compose reference_answer failed")
        return ""

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
            self._stream_interviewer_message(message)
            return message
        # 八股库真题：用规划阶段润色后的口头题面；参考答案优先题库要点
        bank_q = str(q.get("bank_question") or "").strip()
        if q.get("type") == "ba_gu" and bank_q:
            message = str(q.get("text") or bank_q).strip() or bank_q
            pq["pending_asked_text"] = message
            pq["pending_reference_answer"] = self._usable_reference(
                q.get("bank_answer"), q, message
            )
            self._stream_interviewer_message(message)
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
            + "\n要求：只围绕一个关键问点问出一道具体、自然的问题；结合简历与对话语境润色，可适当发挥衔接，严禁照搬素材/题库原句；"
            "严禁把多个问点串成一长串；"
            "若本题考点不在白名单内，禁止说简历提到过，直接按目标岗位提问即可"
        )
        streaming_ask = hasattr(self.llm, "emit_tokens")
        raw: dict = {}
        if streaming_ask:
            question = self.llm.chat_text(ASK_QUESTION_STREAM_SYSTEM, user)
            ref_answer = ""
        else:
            raw = self.llm.chat_json(ASK_QUESTION_SYSTEM, user)
            if not isinstance(raw, dict):
                raw = {}
            question = str(raw.get("question") or "").strip()
            ref_answer = str(raw.get("reference_answer") or "").strip()
            if not question:
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
                if streaming_ask:
                    q2 = self.llm.chat_text(ASK_QUESTION_STREAM_SYSTEM, retry_user).strip()
                    if (
                        q2
                        and not _looks_like_vague_orchestration(q2)
                        and not _conflicts_historical_question(q2, asked_blobs)
                    ):
                        question = q2
                else:
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
        pq["pending_reference_answer"] = self._usable_reference(ref_answer, q, question)
        if not streaming_ask:
            self._stream_interviewer_message(question)
        return question
