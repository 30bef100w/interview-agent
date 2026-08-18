"""八股必须从题库抽取：硬卡目标岗位，禁止同企业串岗凑数。"""
from app.services import knowledge_retrieval as kr
from app.services.interviewer_engine import InterviewEngine
from app.services.job_roles import resolve_company_id, resolve_target_roles
from tests.test_state_machine import PROFILE, RESUME_RAW, FakeLlm


def test_pick_bagu_prefers_company_originals():
    roles = resolve_target_roles("Java 后端")
    cid = resolve_company_id("腾讯")
    hits = kr.pick_bagu_questions(roles=roles, company=cid, n=4)
    assert len(hits) == 4
    assert all(h.get("category") == "bagu" for h in hits)
    assert all(set(h.get("roles") or []) & set(roles) for h in hits)
    assert hits[0].get("company") == "tencent"


def test_pick_bagu_never_cross_role_for_company_fill():
    """企业×岗位交叉为空时：只补同岗位题，绝不拿同企业其他岗位凑。"""
    cid = resolve_company_id("字节跳动")
    roles = ["big_data"]
    hits = kr.pick_bagu_questions(roles=roles, company=cid, n=4)
    assert len(hits) == 4
    assert all(h.get("category") == "bagu" for h in hits)
    assert all(set(h.get("roles") or []) & set(roles) for h in hits)


def test_pick_bagu_agent_alibaba_not_java_threadlocal():
    """Agent + 阿里：不得抽出 Java ThreadLocal / Cookie 上下文题。"""
    roles = resolve_target_roles("AI Agent 开发")
    cid = resolve_company_id("阿里巴巴")
    assert "agent_dev" in roles
    hits = kr.pick_bagu_questions(roles=roles, company=cid, n=12)
    assert hits
    assert all(set(h.get("roles") or []) & set(roles) for h in hits)
    for h in hits:
        q = (h.get("question") or "").lower()
        assert "threadlocal" not in q
        assert "cookie解析" not in (h.get("question") or "")


def test_engine_bytedance_badge_only_for_target_company():
    llm = FakeLlm()
    engine = InterviewEngine(llm)
    state, _ = engine.create(
        1, RESUME_RAW, PROFILE, 8, "specialized", "ba_gu", "数据开发 / 大数据", "字节跳动"
    )
    bagu = [q for q in state.plan if q["type"] == "ba_gu"]
    assert bagu
    assert all(q.get("from_bank") for q in bagu)
    # 交叉为空时允许其他企业同岗位补齐（岗位硬卡优先于企业徽标）
    assert all(q.get("bank_question") for q in bagu)


def test_engine_injects_bagu_from_bank_not_planner():
    llm = FakeLlm()
    engine = InterviewEngine(llm)
    state, _ = engine.create(
        1, RESUME_RAW, PROFILE, 8, "full", "full", "Java 后端", "腾讯"
    )
    bagu = [q for q in state.plan if q["type"] == "ba_gu"]
    assert bagu
    assert all(q.get("from_bank") for q in bagu)
    assert all(q.get("bank_question") for q in bagu)
    assert not any(
        q["type"] == "ba_gu" and not q.get("from_bank") for q in state.plan
    )
    assert any(q.get("original_company") == "腾讯" for q in bagu)


def test_ask_bagu_uses_selected_spoken_from_bank():
    """八股仍锚定题库原题；口头问法用规划阶段选中的 text（可润色）。"""
    llm = FakeLlm()
    engine = InterviewEngine(llm)
    state, _ = engine.create(
        1, RESUME_RAW, PROFILE, 8, "specialized", "ba_gu", "Java 后端", "腾讯"
    )
    assert state.plan
    assert all(q["type"] == "ba_gu" and q.get("bank_question") for q in state.plan)
    first = state.plan[0]
    spoken = first.get("text") or first["bank_question"]
    calls_before = len(llm.calls)
    state, message = engine.handle_intro(state, "我叫张三")
    assert message == spoken
    assert len(llm.calls) == calls_before
    assert not message.strip().upper().startswith("Q1")


def test_noisy_meta_bagu_filtered():
    from app.services.knowledge_retrieval import _is_noisy

    assert _is_noisy({"question": "AI / LLM Interview References", "roles": ["llm"]})
    assert _is_noisy({"question": "Java 后端面试哪些知识点是重点？", "roles": ["java_backend"]})
    assert not _is_noisy(
        {"question": "HashMap 和 ConcurrentHashMap 有什么区别？", "roles": ["java_backend"]}
    )


def test_strip_catalog_prefix():
    assert (
        InterviewEngine._strip_catalog_prefix("Q1: 用户登录后如何传上下文？")
        == "用户登录后如何传上下文？"
    )
    assert InterviewEngine._strip_catalog_prefix("Q2：什么是 RAG？") == "什么是 RAG？"


def test_ensure_spoken_question_rewrites_title():
    spoken = InterviewEngine._ensure_spoken_question(
        "epoll线程安全分析", "epoll线程安全分析"
    )
    assert spoken.endswith("？")
    assert "epoll" in spoken
    assert InterviewEngine._is_spoken_question(spoken)
    assert InterviewEngine._is_spoken_question("HashMap 和 ConcurrentHashMap 有什么区别？")
    assert not InterviewEngine._is_spoken_question("epoll线程安全分析")


def test_bytedance_big_data_stays_on_role():
    llm = FakeLlm()
    engine = InterviewEngine(llm)
    state, _ = engine.create(
        1, RESUME_RAW, PROFILE, 8, "specialized", "ba_gu", "数据开发 / 大数据", "字节跳动"
    )
    bagu = [q for q in state.plan if q["type"] == "ba_gu"]
    assert bagu
    assert all(q.get("from_bank") for q in bagu)
    assert all(q.get("bank_question") for q in bagu)
