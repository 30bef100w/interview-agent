"""项目拷打链生成（面试规划师职责之一）：简历项目 + 目标岗位 + 多路真题 → LLM 现编拷打链。

拷打链结构：[{trigger, question, intent}]——trigger 是追问触发条件，面试中答到点就顺链深挖。
链由模型现编（模拟真人面试官怎么追），不要求照搬原题；多路召回提供「岗位考什么」与「这类项目真人怎么问」。

与题单分离：题单主问由规划官出；拷打链仅用于主问之后的追问，二者互不替代。
"""

PROJECT_CHAIN_SYSTEM = """你是资深面试官，负责为候选人的一个简历项目生成"拷打链"。

最高原则：【岗位定考察能力，场景真题定真人问法，项目是素材】。
链必须由你现编，模拟真人面试官顺着项目往下挖；参考面经的考点与追问节奏，禁止逐字照搬原题。
所有追问必须能对应【目标岗位】能力模型；场景面经须改写拧到岗位视角，禁止串岗照搬。

输入分两路（都要吃，且都必须经过岗位过滤后的素材）：
A. 目标岗位相关真题 → 决定考什么能力（如 Agent 的工具调用/RAG，Java 的并发一致性）
B. 本项目业务/技术场景真题（已按岗位过滤）→ 决定真人怎么挖这类项目（如本地生活的券/缓存/订单状态）

规则：
1. 综合 A+B 编链：用岗位视角拧项目，同时保留场景真题里「像真人」的业务追问点；
   不要只按岗位空编「怎么设计多 Agent」，也不要只按项目原栈出脱离岗位的课设题。
   例：目标 Agent + 本地生活项目 → 既问 Agent/工具编排怎么落在该业务，也参考场景真题里券、缓存、高并发等会被追的点，再改写成岗位口吻
   例：目标 Java 后端 + 同一项目 → 深挖缓存/并发/一致性，问法对齐场景真题
2. 每个拷打节点 = {"when": 候选人在回答中提到什么时触发（具体到技术点/关键词）, "problem": 示例追问问题, "intent": "考什么（必须对应目标岗位）", "source_question_ids": ["引用的原始召回题ID"]}
   source_question_ids 只能填写输入素材中真实出现的 id；无法对应时填空数组，不得编造。
3. 生成 4-6 个并列追问节点；节点之间不代表先后顺序，不要输出 NEXT 或递进关系
4. 只输出 JSON，不要任何其他文字

Respond ONLY with this JSON schema:
{
  "project": "项目名",
  "chains": [
    {"when": "候选人提到X", "problem": "追问问题", "intent": "考什么", "source_question_ids": []}
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
        qid = str(
            h.get("canonical_question_id")
            or h.get("question_id")
            or h.get("graph_canonical_question_id")
            or h.get("graph_question_id")
            or ""
        ).strip()
        ident = f"[id={qid}] " if qid else ""
        company = str(h.get("company") or "").strip()
        company_hint = f"[企业={company}] " if company else ""
        lines.append(f"- {ident}{company_hint}{q}" + (f"（要点：{ans[:100]}）" if ans else ""))
        if len(lines) >= limit:
            break
    return lines


def _project_chain_user(
    p: dict,
    *,
    target_role: str,
    roles: list[str],
    asked: set[str],
    company: str | None,
    retrieval,
    prepared_material: tuple[list[dict], list[dict]] | None = None,
) -> tuple[str, str] | None:
    """准备单个项目的 LLM user prompt；无项目名则跳过。"""
    name = str(p.get("name") or "").strip()
    tech = [str(x) for x in (p.get("tech_stack") or p.get("tech") or []) if str(x).strip()]
    desc = str(p.get("desc") or p.get("description") or "")
    scene_tags = [str(x) for x in (p.get("scene_tags") or []) if str(x).strip()]
    if not name:
        return None

    role_hits: list[dict] = []
    scene_hits: list[dict] = []
    if prepared_material is not None:
        role_hits, scene_hits = prepared_material
    else:
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
            role_hits = retrieval.sanitize_hits(
                role_hits, roles=roles, company=company, require_role=True
            )
            if scene_tags or tech:
                company_scene: list[dict] = []
                if company:
                    company_scene = retrieval.search_questions(
                        roles=roles,
                        company=company,
                        skills=tech,
                        scenes=scene_tags,
                        category="project",
                        asked_norms=asked,
                        top_n=5,
                        min_score=10,
                    )
                untagged_scene = retrieval.search_questions(
                    roles=roles,
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
                proj_hits = retrieval.sanitize_hits(
                    proj_hits, roles=roles, company=company, require_role=True
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
                scene_hits = retrieval.sanitize_hits(
                    scene_hits, roles=roles, company=company, require_role=True
                )
        elif scene_tags or tech:
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
        + "\n\n【B. 本项目场景相关真实面经（已岗位过滤，须改写拧到目标岗位）】\n"
        + ("\n".join(scene_lines) if scene_lines else "（无命中）")
        + "\n\n请综合 A+B 现编该项目的拷打链（模拟真人追问，勿照搬原题）。"
    )
    return name, user


def build_project_chains(
    llm,
    profile: dict,
    target_role: str = "",
    retrieval=None,
    role_ids: list[str] | None = None,
    asked_norms: set[str] | None = None,
    company: str | None = None,
    session_id: int | None = None,
    project_material: list[dict] | None = None,
    role_material: list[dict] | None = None,
) -> list[dict]:
    """对简历每个项目（≤3 个）各生成一条完整拷打链。失败跳过单项目，不阻塞面试。"""
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
    prepared: list[tuple[str, str]] = []
    for index, p in enumerate(projects[:3]):
        prepared_material = None
        if project_material is not None:
            prepared_material = (list(role_material or []), [
                hit for hit in project_material if hit.get("graph_project_id") == f"p{index + 1}"
            ])
        item = _project_chain_user(
            p,
            target_role=target_role,
            roles=roles,
            asked=asked,
            company=company,
            retrieval=retrieval,
            prepared_material=prepared_material,
        )
        if item:
            prepared.append(item)

    if not prepared:
        return []

    chains_out: list[dict] = []
    calls = [(PROJECT_CHAIN_SYSTEM, user) for _, user in prepared]
    try:
        results = llm.chat_json_many(calls)
    except Exception:
        results = []
        for _, user in prepared:
            try:
                results.append(llm.chat_json(PROJECT_CHAIN_SYSTEM, user, max_retries=1))
            except Exception as exc:  # noqa: BLE001
                from app.services.session_guard_log import log_guard

                log_guard(
                    session_id,
                    "project_chain_skipped",
                    reason=type(exc).__name__,
                )
                results.append({})

    valid_source_ids: set[str] = set()
    for _, user in prepared:
        # IDs are embedded in the material lines as [id=...]. This set is only
        # a safety filter; an empty set is allowed for legacy hits without IDs.
        import re

        valid_source_ids.update(re.findall(r"\[id=([^\]\s]+)\]", user))

    for (name, _), result in zip(prepared, results, strict=False):
        try:
            chains = (result or {}).get("chains") or []
            if chains:
                # 给每个生成节点稳定 ID，运行时反馈可以精确回写到链节点。
                normalized = []
                for index, chain in enumerate(chains[:6], 1):
                    if not isinstance(chain, dict):
                        continue
                    item = dict(chain)
                    # 新格式使用 when/problem；保留旧 trigger/question 别名，
                    # 让历史状态和旧规划逻辑继续可读。
                    item.setdefault("when", item.get("trigger", ""))
                    item.setdefault("problem", item.get("question", ""))
                    item.setdefault("trigger", item.get("when", ""))
                    item.setdefault("question", item.get("problem", ""))
                    item.setdefault("chain_node_id", f"{name}#node-{index}")
                    ids = item.get("source_question_ids")
                    item["source_question_ids"] = (
                        [str(x) for x in ids if str(x).strip() and str(x) in valid_source_ids]
                        if isinstance(ids, list)
                        else []
                    )
                    normalized.append(item)
                if normalized:
                    chains_out.append({"project": name, "chains": normalized})
                else:
                    from app.services.session_guard_log import log_guard

                    log_guard(session_id, "project_chain_empty", project=name)
            else:
                from app.services.session_guard_log import log_guard

                log_guard(session_id, "project_chain_empty", project=name)
        except Exception as exc:  # noqa: BLE001
            from app.services.session_guard_log import log_guard

            log_guard(
                session_id,
                "project_chain_skipped",
                project=name,
                reason=type(exc).__name__,
            )
    return chains_out


def chain_block_for(project_chains: list[dict], project_name: str) -> str:
    """取出某项目的拷打链 → prompt 注入文本。"""
    for pc in project_chains:
        if pc.get("project") == project_name:
            lines = [f"【{project_name} 拷打链】"]
            for i, c in enumerate(pc.get("chains") or [], 1):
                node_id = c.get("chain_node_id") or f"{project_name}#node-{i}"
                tg_id = c.get("tg_probe_id")
                tg_hint = f"；TG节点ID：{tg_id}" if tg_id else ""
                source_ids = ",".join(str(x) for x in (c.get("source_question_ids") or []) if str(x).strip())
                source_hint = f"；来源题目：{source_ids}" if source_ids else ""
                lines.append(
                    f"{i}. 节点ID：{node_id}{tg_hint}{source_hint}；触发：{c.get('when') or c.get('trigger')} → 追问：{c.get('problem') or c.get('question')}（考：{c.get('intent')}）"
                )
            return "\n".join(lines)
    return ""
