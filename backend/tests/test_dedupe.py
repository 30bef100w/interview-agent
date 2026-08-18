"""去重：跨场挡换句重复，不永封考点；空泛编排对空泛编排拦截。"""
from app.schemas.api import CreateSessionRequest
from app.services.interviewer_engine import (
    InterviewEngine,
    _conflicts_bagu_knowledge,
    _conflicts_historical_question,
    _is_similar_question,
    _looks_like_vague_orchestration,
    _topic_key_tags,
)
from app.services.knowledge_retrieval import _asked_score_penalty


def test_near_duplicate_mindbridge_mcp_blocked_across_sessions():
    hist = [
        "MindBridge：通过 MCP 协议封装 Excel 写入和邮件预警工具，请讲实现",
    ]
    cand = (
        "在MindBridge平台中，你提到通过MCP协议封装了Excel写入和邮件预警两个工具。"
        "请详细讲讲MCP协议封装工具的具体实现过程"
    )
    assert _is_similar_question(hist[0], cand)
    assert _conflicts_historical_question(cand, hist)


def test_mcp_later_with_new_angle_is_allowed():
    hist = [
        "MindBridge：通过 MCP 协议封装 Excel 写入和邮件预警工具，请讲实现",
    ]
    cand = "MCP 工具调用失败时，重试、超时和降级你怎么设计？请给一个具体失败链路。"
    assert not _conflicts_historical_question(cand, hist)


def test_vague_orchestration_blocks_another_vague():
    hist = ["请谈谈如何编排多智能体协作系统？"]
    cand = "你怎么设计多 Agent 编排流程？"
    assert _looks_like_vague_orchestration(hist[0])
    assert _looks_like_vague_orchestration(cand)
    assert _conflicts_historical_question(cand, hist)


def test_cache_penetrate_vs_breakdown_are_different_angles():
    hist = ["请说明缓存穿透是什么，怎么防？"]
    cand = "缓存击穿和热点 key 怎么处理？"
    assert not (_topic_key_tags(hist[0]) & _topic_key_tags(cand))
    assert not _conflicts_historical_question(cand, hist)


def test_dedupe_plan_keeps_rag_when_mcp_exists():
    engine = InterviewEngine(llm=None)  # type: ignore[arg-type]
    plan = [
        {
            "type": "project",
            "topic": "工具调用与外部服务集成",
            "text": "MindBridge 的 MCP 工具封装与可靠性",
        },
        {
            "type": "project",
            "topic": "RAG 链路",
            "text": "MindBridge 里 RAG 检索与重排怎么做",
        },
    ]
    kept = engine._dedupe_plan(plan, [])
    assert len(kept) == 2


def test_dedupe_plan_drops_historical_similar():
    engine = InterviewEngine(llm=None)  # type: ignore[arg-type]
    hist = ["MindBridge：通过 MCP 协议封装 Excel 写入和邮件预警工具，请讲实现"]
    plan = [
        {
            "type": "project",
            "topic": "MCP",
            "text": "请详细讲讲 MindBridge 通过 MCP 协议封装工具的实现过程",
        },
        {
            "type": "project",
            "topic": "RAG",
            "text": "MindBridge 的检索与重排怎么做",
        },
    ]
    kept = engine._dedupe_plan(plan, hist)
    assert len(kept) == 1
    assert "RAG" in kept[0]["topic"]


def test_similar_reword_still_conflicts():
    a = "MindBridge 里 MCP 工具怎么封装和注册？"
    b = "请详细讲讲 MindBridge 通过 MCP 协议封装工具的实现过程"
    assert _conflicts_historical_question(b, [a])


def test_asked_score_penalty_exact_and_near():
    asked = {"mindbridge通过mcp协议封装excel写入和邮件预警工具请讲实现"}
    exact = "mindbridge通过mcp协议封装excel写入和邮件预警工具请讲实现"
    near = "mindbridge通过mcp协议封装excel写入和邮件预警"
    fresh = "请说明jvm垃圾回收分代与停顿优化"
    assert _asked_score_penalty(exact, asked) <= 0.02
    assert _asked_score_penalty(near, asked) <= 0.1
    assert _asked_score_penalty(fresh, asked) == 1.0


def test_create_session_default_dedup_is_all():
    req = CreateSessionRequest(
        resume_id=1,
        interview_mode="full",
        interview_type="full",
    )
    assert req.dedup_scope == "all"


def test_top_up_after_dedupe_regenerates_projects_not_bagu():
    """去重砍光项目后，空位应重出项目（可点名简历），禁止八股填坑。"""
    from app.schemas.interview import InterviewState

    engine = InterviewEngine(llm=None)  # type: ignore[arg-type]
    engine._plan_project_n = 3
    engine._plan_ba_gu_n = 2
    state = InterviewState(
        session_id=1,
        resume_raw="",
        total_rounds=6,
        profile={
            "projects": [
                {"name": "MindBridge", "tech_stack": ["Spring AI", "RAG"]},
                {"name": "知秦", "tech_stack": ["Redis", "Canal"]},
            ]
        },
        avoid_topics=[
            "MindBridge：通过 MCP 协议封装 Excel 写入和邮件预警工具，请讲实现",
            "请谈谈如何编排多智能体协作系统？",
        ],
        project_chains=[
            {
                "project": "MindBridge",
                "chains": [
                    {
                        "trigger": "提到 RAG",
                        "question": "MindBridge 里口语化提问如何保证召回危机干预资料？",
                        "intent": "高风险召回",
                    },
                    {
                        "trigger": "提到流式",
                        "question": "MindBridge 连续提问时上下文窗口怎么截断和摘要？",
                        "intent": "上下文管理",
                    },
                ],
            },
            {
                "project": "知秦",
                "chains": [
                    {
                        "trigger": "提到 Canal",
                        "question": "知秦里 Canal 延迟导致营业时间旧数据，兜底怎么做？",
                        "intent": "缓存一致性",
                    }
                ],
            },
        ],
        plan=[
            {
                "type": "ba_gu",
                "topic": "LangGraph",
                "text": "LangGraph 和 LangChain 有什么区别？",
            }
        ],
    )
    # 模拟：项目题全被去重删光，只剩 1 道八股
    topped = engine._top_up_plan(state, target_n=6, mode="full")
    projects = [q for q in topped if q.get("type") == "project"]
    bagus = [q for q in topped if q.get("type") == "ba_gu"]
    assert len(topped) >= 5
    assert len(projects) >= 3, f"应重出项目题，实际 plan={topped}"
    # 八股不得超过配额（可因原有 1 道保留；不得用八股填满空位）
    assert len(bagus) <= 2
    blob = " ".join(f"{p.get('topic')} {p.get('text')}" for p in projects)
    assert "MindBridge" in blob or "知秦" in blob


def test_bagu_langchain_langgraph_different_angles_allowed():
    a = "LangChain 的核心组件有哪些？请结合 Chain 说明。"
    b = "LangGraph 怎么用状态图构建带循环的 Agent 工作流？"
    assert not _conflicts_bagu_knowledge(b, [a])


def test_bagu_same_bank_entry_rewritten_blocked():
    a = "LangChain 的核心组件有哪些？请结合实际使用说明如何用 Chain 串联它们？"
    b = "请结合实际使用说明，LangChain 的核心组件有哪些？如何用 Chain 串联它们？"
    assert _conflicts_bagu_knowledge(b, [a])


def test_dedupe_plan_keeps_framework_angles_drops_same_entry():
    engine = InterviewEngine(llm=None)  # type: ignore[arg-type]
    plan = [
        {
            "type": "ba_gu",
            "topic": "LangChain",
            "text": "LangChain 核心组件有哪些？请结合 Chain 说明。",
            "bank_question": "LangChain 的核心组件有哪些？请结合实际使用说明如何用 Chain 串联它们？",
        },
        {
            "type": "ba_gu",
            "topic": "LangGraph",
            "text": "LangGraph 怎么构建带循环的复杂 Agent 工作流？",
            "bank_question": "什么是 LangGraph？它如何帮助我们构建复杂的 Agent 工作流？",
        },
        {
            "type": "ba_gu",
            "topic": "LangChain 复述",
            "text": "请结合实际使用说明，LangChain 的核心组件有哪些？如何用 Chain 串联它们？",
            "bank_question": "LangChain 的核心组件有哪些？请结合实际使用说明如何用 Chain 串联它们？",
        },
    ]
    kept = engine._dedupe_plan(plan, [])
    bagu = [q for q in kept if q["type"] == "ba_gu"]
    assert len(bagu) == 2
    texts = " ".join(q["text"] for q in bagu)
    assert "LangChain 核心组件" in texts
    assert "LangGraph" in texts
    assert "复述" not in " ".join(q["topic"] for q in bagu)
