"""项目拷打链生成（面试规划师职责之一）：简历项目 + 目标岗位 + 多路真题 → LLM 现编拷打链。

拷打链结构：[{trigger, question, intent}]——trigger 是追问触发条件，面试中答到点就顺链深挖。
链由模型现编（模拟真人面试官怎么追），不要求照搬原题；多路召回提供「岗位考什么」与「这类项目真人怎么问」。
"""

PROJECT_CHAIN_SYSTEM = """你是资深面试官，负责为候选人的一个简历项目生成"拷打链"。

最高原则：【岗位定考察能力，场景真题定真人问法，项目是素材】。
链必须由你现编，模拟真人面试官顺着项目往下挖；参考面经的考点与追问节奏，禁止逐字照搬原题。

输入分两路（都要吃）：
A. 目标岗位相关真题 → 决定考什么能力（如 Agent 的工具调用/RAG，搜广推的样本特征，Java 的并发一致性）
B. 本项目业务/技术场景真题 → 决定真人怎么挖这类项目（如本地生活的券/缓存/订单状态；不要无视）

规则：
1. 综合 A+B 编链：用岗位视角拧项目，同时保留场景真题里「像真人」的业务追问点；
   不要只按岗位空编「怎么设计多 Agent」，也不要只按项目原栈出脱离岗位的课设题。
   例：目标 Agent + 点评/本地生活项目 → 既问 Agent/工具编排怎么落在该业务，也参考点评真题里券、缓存、高并发等会被追的点，再改写成该岗位口吻
   例：目标 Java 后端 + 同一项目 → 深挖缓存/并发/一致性，问法对齐场景真题
2. 每条拷打链 = {"trigger": 候选人在回答中提到什么时触发（具体到技术点/关键词）, "question": 顺着 trigger 追问的具体问题, "intent": "面试官想考什么"}
3. 生成 4-6 条，从浅到深
4. 只输出 JSON，不要任何其他文字

Respond ONLY with this JSON schema:
{
  "project": "项目名",
  "chains": [
    {"trigger": "候选人提到X", "question": "追问问题", "intent": "考什么"}
  ]
}"""


def _dedupe_lines(hits: list[dict], limit: int) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for h in hits:
        q = str(h.get("question") or "").strip()
        if not q or q in seen:
            continue
        seen.add(q)
        ans = (h.get("answer") or "").strip()
        lines.append(f"- {q}" + (f"（要点：{ans[:100]}）" if ans else ""))
        if len(lines) >= limit:
            break
    return lines


def build_project_chains(
    llm,
    profile: dict,
    target_role: str = "",
    retrieval=None,
    role_ids: list[str] | None = None,
    asked_norms: set[str] | None = None,
    company: str | None = None,
) -> list[dict]:
    """对简历每个项目（≤3 个）生成拷打链。失败跳过，不阻塞面试。

    多路召回：目标岗位真题 + 本项目场景/技术栈真题，一并喂给模型现编。
    有目标企业时：场景路同时吃「该企业标签题」与「无企业标签通用题」。
    """
    projects = profile.get("projects") or []
    if not projects:
        return []
    if retrieval is None:
        from app.services import knowledge_retrieval as retrieval

    roles = list(role_ids or [])
    if not roles and target_role:
        from app.services.job_roles import resolve_target_roles

        roles = resolve_target_roles(target_role)

    asked = asked_norms or set()
    chains_out: list[dict] = []
    for p in projects[:3]:
        name = str(p.get("name") or "").strip()
        tech = [str(x) for x in (p.get("tech_stack") or p.get("tech") or []) if str(x).strip()]
        desc = str(p.get("desc") or p.get("description") or "")
        scene_tags = [str(x) for x in (p.get("scene_tags") or []) if str(x).strip()]
        if not name:
            continue

        role_hits: list[dict] = []
        scene_hits: list[dict] = []
        if roles:
            role_hits += retrieval.search_questions(
                roles=roles,
                category="project",
                asked_norms=asked,
                top_n=6,
                min_score=10,
            )
            role_hits += retrieval.search_questions(
                roles=roles, asked_norms=asked, top_n=6, min_score=10
            )
        if scene_tags or tech:
            company_scene: list[dict] = []
            if company:
                company_scene += retrieval.search_questions(
                    roles=None,
                    company=company,
                    skills=tech,
                    scenes=scene_tags,
                    category="project",
                    asked_norms=asked,
                    top_n=5,
                    min_score=10,
                )
            untagged_scene = retrieval.search_questions(
                roles=None,
                skills=tech,
                scenes=scene_tags,
                category="project",
                asked_norms=asked,
                top_n=6,
                min_score=15,
            )
            proj_hits = retrieval.search_projects(
                name, tech, scene_tags, top_n=5, asked_norms=asked
            )
            if hasattr(retrieval, "merge_company_and_untagged"):
                scene_hits = retrieval.merge_company_and_untagged(
                    company_scene,
                    untagged_scene,
                    company=company,
                    limit=8,
                    extra=proj_hits,
                )
            else:
                scene_hits = list(company_scene) + [
                    h for h in untagged_scene if not h.get("company")
                ] + list(proj_hits)
        elif not roles:
            scene_hits += retrieval.search_projects(
                name, tech, scene_tags, top_n=4, asked_norms=asked
            )

        role_lines = _dedupe_lines(role_hits, 6)
        scene_lines = _dedupe_lines(scene_hits, 6)

        role_hint = f"\n【目标岗位】{target_role}\n" if target_role else ""
        user = (
            f"【项目】{name}\n"
            f"技术栈：{'、'.join(tech) or '（未标注）'}\n"
            f"描述：{desc[:300]}\n"
            f"场景标签：{'、'.join(scene_tags) or '（未标注）'}"
            + role_hint
            + "\n\n【A. 目标岗位相关真实面经/高频题】\n"
            + ("\n".join(role_lines) if role_lines else "（无命中）")
            + "\n\n【B. 本项目场景相关真实面经/高频题】\n"
            + ("\n".join(scene_lines) if scene_lines else "（无命中）")
            + "\n\n请综合 A+B 现编该项目的拷打链（模拟真人追问，勿照搬原题）。"
        )
        try:
            result = llm.chat_json(PROJECT_CHAIN_SYSTEM, user, max_retries=1)
            chains = result.get("chains") or []
            if chains:
                chains_out.append({"project": name, "chains": chains[:6]})
        except Exception:  # noqa: BLE001  拷打链失败跳过该项目
            continue
    return chains_out


def chain_block_for(project_chains: list[dict], project_name: str) -> str:
    """取出某项目的拷打链 → prompt 注入文本。"""
    for pc in project_chains:
        if pc.get("project") == project_name:
            lines = [f"【{project_name} 拷打链】"]
            for i, c in enumerate(pc.get("chains") or [], 1):
                lines.append(
                    f"{i}. 触发：{c.get('trigger')} → 追问：{c.get('question')}（考：{c.get('intent')}）"
                )
            return "\n".join(lines)
    return ""
