"""多路召回：有目标岗位时仍召回项目场景真题，并分区喂给编链。"""
from app.services import knowledge_retrieval as kr
from app.services.project_cross import PROJECT_CHAIN_SYSTEM, build_project_chains


class _RecordingRetrieval:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def search_questions(self, **kwargs):
        self.calls.append(("search_questions", kwargs))
        scenes = kwargs.get("scenes") or []
        roles = kwargs.get("roles") or []
        if roles:
            return [
                {
                    "question": "Agent 里工具调用失败怎么重试与降级？",
                    "answer": "重试预算与兜底",
                    "roles": list(roles),
                    "category": "project",
                }
            ]
        if scenes:
            return [
                {
                    "question": "秒杀场景下 Redis 库存如何保证不超卖？",
                    "answer": "lua/扣减原子性",
                    "business_scene": list(scenes),
                    "category": "project",
                }
            ]
        return []

    def search_projects(self, name, skills, scenes, top_n=4, asked_norms=None):
        self.calls.append(
            (
                "search_projects",
                {
                    "name": name,
                    "skills": skills,
                    "scenes": scenes,
                    "top_n": top_n,
                    "asked_norms": asked_norms,
                },
            )
        )
        return [
            {
                "question": f"{name}：优惠券超发怎么防？",
                "answer": "库存预扣",
                "category": "project",
                "business_scene": scenes or ["外卖/本地生活"],
            }
        ]


class _ChainLlm:
    def __init__(self) -> None:
        self.last_user = ""

    def chat_json(self, system: str, user: str, **_kwargs) -> dict:
        self.last_user = user
        assert "拷打链" in system or PROJECT_CHAIN_SYSTEM[:20] in system
        return {
            "project": "知秦",
            "chains": [
                {
                    "trigger": "提到 Redis",
                    "question": "库存扣减如何保证原子性？",
                    "intent": "并发正确性",
                }
            ],
        }


def test_format_dual_hits_has_both_sections():
    text = kr.format_dual_hits(
        [{"question": "JVM 有哪些垃圾回收器？", "roles": ["java_backend"], "era": "2025"}],
        [
            {
                "question": "点评优惠券怎么防刷？",
                "business_scene": ["外卖/本地生活"],
                "category": "project",
            }
        ],
    )
    assert "【A. 目标岗位相关" in text
    assert "【B. 简历项目场景相关" in text
    assert "JVM" in text
    assert "优惠券" in text
    assert "综合 A+B" in text or "交叉" in text


def test_build_project_chains_recalls_role_and_scene():
    retrieval = _RecordingRetrieval()
    llm = _ChainLlm()
    profile = {
        "projects": [
            {
                "name": "知秦",
                "tech_stack": ["Redis", "Spring Boot"],
                "scene_tags": ["外卖/本地生活"],
                "desc": "文旅本地生活",
            }
        ]
    }
    out = build_project_chains(
        llm,
        profile,
        target_role="AI Agent 工程师",
        retrieval=retrieval,
        role_ids=["ai_agent"],
    )
    assert out and out[0]["project"] == "知秦"
    assert any(c[0] == "search_questions" and c[1].get("roles") for c in retrieval.calls)
    assert any(
        c[0] == "search_questions"
        and not c[1].get("roles")
        and c[1].get("scenes") == ["外卖/本地生活"]
        for c in retrieval.calls
    )
    assert any(c[0] == "search_projects" for c in retrieval.calls)
    assert "【A. 目标岗位相关" in llm.last_user
    assert "【B. 本项目场景相关" in llm.last_user
    assert "秒杀" in llm.last_user or "优惠券" in llm.last_user
    assert "工具调用" in llm.last_user


def test_merge_hits_dedupes():
    a = [{"question": "同一题"}, {"question": "题A"}]
    b = [{"question": "同一题"}, {"question": "题B"}]
    merged = kr.merge_hits(a, b, limit=10)
    assert [h["question"] for h in merged] == ["同一题", "题A", "题B"]


def test_merge_company_and_untagged_interleaves():
    company_hits = [
        {"question": "腾讯原题1", "company": "tencent"},
        {"question": "腾讯原题2", "company": "tencent"},
        {"question": "别家题", "company": "alibaba"},
    ]
    untagged = [
        {"question": "通用场景1"},
        {"question": "通用场景2"},
        {"question": "误带企业", "company": "bytedance"},
    ]
    merged = kr.merge_company_and_untagged(
        company_hits, untagged, company="tencent", limit=6
    )
    qs = [h["question"] for h in merged]
    assert "腾讯原题1" in qs and "通用场景1" in qs
    assert "别家题" not in qs
    assert "误带企业" not in qs
    # 交错：先企业再无标签
    assert qs[0] == "腾讯原题1"
    assert qs[1] == "通用场景1"


def test_format_dual_hits_marks_untagged_when_company():
    text = kr.format_dual_hits(
        [{"question": "岗位题", "roles": ["ai_agent"], "company": "tencent"}],
        [
            {"question": "企业场景题", "company": "tencent", "business_scene": ["外卖/本地生活"]},
            {"question": "通用场景题", "business_scene": ["外卖/本地生活"]},
        ],
        company="tencent",
        company_label="腾讯",
    )
    assert "【企业原题·腾讯】" in text
    assert "【通用·无企业标签】" in text
    assert "企业场景题" in text and "通用场景题" in text
