"""终评：汇总、按轮拆条、空答/幻觉消毒。"""
from __future__ import annotations

import logging

from app.prompts.interview import FINAL_REPORT_SYSTEM
from app.schemas.interview import InterviewState

from .constants import NON_ANSWER_MAX_SCORE
from .guards import (
    filter_strengths,
    is_non_answer,
    looks_like_rubric,
    sanitize_score_fields,
)

logger = logging.getLogger(__name__)


class ReportMixin:
    def finish_interview(self, state: InterviewState):
        from app.observability.node_trace import trace_node

        state.stage = "FINISHED"
        with trace_node("finish_interview", session_id=state.session_id):
            try:
                report = self.llm.chat_json(FINAL_REPORT_SYSTEM, self._report_user(state))
            except Exception:
                logger.exception(
                    "finish_interview json failed session=%s", state.session_id
                )
                report = {
                    "summary": "终评模型输出异常，面试过程已保存。可稍后在网页查看本场记录。",
                    "overall_score": None,
                    "dimension_scores": {},
                    "per_question": [],
                    "strengths": [],
                    "weaknesses": ["终评生成失败"],
                    "suggestions": ["请到网页打开本场报告或历史记录。"],
                }
            report = self._sanitize_report(state, report)
        return state, report

    # ---------- 反问回答 → 终评（兼容旧会话） ----------

    def handle_ask_back(self, state: InterviewState, answer: str):
        if answer.strip():
            state.history.append({"role": "candidate", "text": answer})
        return self.finish_interview(state)

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
                        qa_lines.append(
                            f"【B. rubric——评分尺子，严禁原样写入 reference_answer】{q['rubric']}"
                        )
                    ans = t.get("answer") or ""
                    qa_lines.append(f"【C. 本轮作答】{ans or '（无作答）'}")
                    if t.get("reference_answer") and not looks_like_rubric(str(t.get("reference_answer"))):
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
                        "reference_answer": (
                            ""
                            if looks_like_rubric(str(t.get("reference_answer") or ""))
                            else str(t.get("reference_answer") or "")
                        ),
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
                    llm_ref = str(llm_item.get("reference_answer") or "").strip()
                    if llm_ref and not looks_like_rubric(llm_ref):
                        item["reference_answer"] = llm_ref
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
            if looks_like_rubric(str(item.get("reference_answer") or "")):
                item["reference_answer"] = ""
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
        scores: list[float] = []
        for item in out:
            try:
                scores.append(float(item.get("score")))
            except (TypeError, ValueError):
                continue
        avg = round(sum(scores) / len(scores), 1) if scores else None
        dims = report.get("dimension_scores")
        dims_empty = not isinstance(dims, dict) or not dims
        dims_floor = False
        if isinstance(dims, dict) and dims:
            try:
                dims_floor = all(float(v) <= 1.01 for v in dims.values())
            except (TypeError, ValueError):
                dims_floor = True
        all_non = bool(state.plan) and all(
            is_non_answer(state.per_question.get(q["qid"], {}).get("answers"))
            for q in state.plan
        )
        if avg is not None and (dims_empty or dims_floor) and not all_non:
            report["dimension_scores"] = {
                "技术深度": avg,
                "项目经验": avg,
                "沟通表达": avg,
                "综合素质": avg,
            }
        if avg is not None and report.get("overall_score") is None:
            report["overall_score"] = avg
        summary = str(report.get("summary") or "")
        if avg is not None and "终评模型输出异常" in summary:
            report["summary"] = (
                f"本场共 {len(out)} 条问答（含追问），过程评分均分 {avg}。"
                "终评模型未产出完整 JSON，报告按面试中已打出的逐题分汇总。"
            )
            if report.get("weaknesses") == ["终评生成失败"]:
                weak = [
                    str(item.get("topic") or "题目")
                    for item in out
                    if float(item.get("score") or 0) <= 3
                ][:4]
                report["weaknesses"] = weak or ["部分题目深度不足"]
                report["suggestions"] = [
                    "建议针对低分题补齐对比、边界与落地细节；网页可查看逐题点评。"
                ]
        return report
