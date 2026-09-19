"""八股从题库抽取：LLM 遴选 + 口头问句 + 企业徽标。"""
from __future__ import annotations

import re

from app.prompts.interview import BAGU_SELECT_SYSTEM

from .guards import _conflicts_bagu_knowledge, _is_similar_question


class BaguMixin:
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
        s = BaguMixin._strip_catalog_prefix(question or "")
        s = s.rstrip("？?。.!！")
        if len(s) <= 28:
            return s or "八股知识"
        return s[:26].rstrip("，,、 ：:") + "…"
