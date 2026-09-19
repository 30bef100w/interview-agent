from app.services.resume_review import (
    assemble_review_tree,
    make_bullet_key,
    make_item_key,
    validate_note_payload,
)


PROFILE = {
    "name": "张三",
    "experience_years": "应届",
    "education": [{"school": "某某大学", "degree": "本科", "major": "计算机", "year": "2024"}],
    "skills": ["Python", "Redis"],
    "experience": [
        {
            "company": "某某科技",
            "role": "后端实习生",
            "duration": "2025.06-2025.09",
            "responsibilities": ["负责订单服务的 Redis 预扣", "参与值班与问题排查"],
        }
    ],
    "projects": [
        {
            "name": "校园二手交易平台",
            "role": "后端",
            "tech_stack": ["Spring Boot", "Redis"],
            "highlights": ["用 Redis 预扣解决超卖", "接入微信支付"],
            "scene_tags": ["电商/交易", "缓存"],
        }
    ],
}


def test_tree_has_whole_bullet_and_highlights():
    tree = assemble_review_tree(PROFILE, [])
    assert tree["name"] == "张三"
    assert tree["skills"] == ["Python", "Redis"]
    intern = tree["experience"][0]
    assert intern["title"] == "某某科技"
    assert intern["bullets"][0]["is_whole"] is True
    assert intern["bullets"][0]["text"] == "整段经历"
    assert [b["text"] for b in intern["bullets"][1:]] == [
        "负责订单服务的 Redis 预扣",
        "参与值班与问题排查",
    ]
    proj = tree["projects"][0]
    assert proj["title"] == "校园二手交易平台"
    assert any(b["text"] == "用 Redis 预扣解决超卖" for b in proj["bullets"])


def test_notes_attach_to_matching_bullet():
    intern_key = make_item_key("experience", "某某科技|后端实习生|2025.06-2025.09")
    bullet = make_bullet_key(intern_key, "负责订单服务的 Redis 预扣")
    notes = [
        {
            "id": 1,
            "kind": "qa",
            "question": "预扣如何保证原子性？",
            "answer": "Lua 脚本。",
            "body": "",
            "section_type": "experience",
            "item_key": intern_key,
            "bullet_key": bullet,
        }
    ]
    tree = assemble_review_tree(PROFILE, notes)
    matched = next(
        b for b in tree["experience"][0]["bullets"] if b["text"] == "负责订单服务的 Redis 预扣"
    )
    assert matched["notes"][0]["question"] == "预扣如何保证原子性？"
    assert tree["experience"][0]["orphan_notes"] == []
    assert tree["unmatched_notes"] == []


def test_orphan_when_bullet_text_changes():
    intern_key = make_item_key("experience", "某某科技|后端实习生|2025.06-2025.09")
    notes = [
        {
            "id": 2,
            "kind": "note",
            "question": "",
            "answer": "",
            "body": "旧 bullet 上的注释",
            "section_type": "experience",
            "item_key": intern_key,
            "bullet_key": "deadbeefdeadbeef",
        }
    ]
    tree = assemble_review_tree(PROFILE, notes)
    assert tree["experience"][0]["orphan_notes"][0]["body"] == "旧 bullet 上的注释"


def test_unmatched_when_item_disappears():
    notes = [
        {
            "id": 3,
            "kind": "note",
            "body": "已删除项目上的笔记",
            "item_key": "gone",
            "bullet_key": "gone-b",
        }
    ]
    tree = assemble_review_tree(PROFILE, notes)
    assert tree["unmatched_notes"][0]["body"] == "已删除项目上的笔记"


def test_original_bullets_from_raw_not_summary():
    raw = """
实习经历
某某科技
后端实习生
2025.06-2025.09
负责项目：“校园二手”是内部交易平台。
我的职责：在保障库存一致的前提下，负责订单 Redis 预扣与回补。
• 构建主进程工具架构（Go schema注册→IPC通信→Renderer分发），统一接线。
• 设计并实现工具schema动态加载，将工具层次化组织并支持按需加载，使用户可自主控制工具暴露范围，在保障隐私
的同时提高调用准确率，经测试正确率提高约32%。
项目经历
校园二手交易平台
2025.03-2025.06
项目背景：二手交易平台，覆盖发布与支付。
• 高并发写链路：针对抢购场景，采用网关令牌桶+业务滑动窗口实现二级限流，约10000请求下系统错误7.1%→0%，利用Lua预扣库存
并配合唯一索引保障一人一单。
专业技能
Java
"""
    profile = {
        "name": "张三",
        "experience": [
            {
                "company": "某某科技",
                "role": "后端实习生",
                "duration": "2025.06-2025.09",
                "responsibilities": ["负责订单 Redis 预扣"],
            }
        ],
        "projects": [
            {
                "name": "校园二手交易平台",
                "role": "后端",
                "highlights": ["用 Redis 预扣解决超卖"],
            },
            {
                "name": "校园二手",
                "role": "实习生项目",
                "highlights": ["这是实习里的子项目摘要"],
            },
        ],
    }
    tree = assemble_review_tree(profile, [], raw_text=raw)
    intern_texts = [b["text"] for b in tree["experience"][0]["bullets"] if not b["is_whole"]]
    assert any("Go schema注册→IPC通信→Renderer分发" in t for t in intern_texts)
    assert any("正确率提高约32%" in t for t in intern_texts)
    assert "负责订单 Redis 预扣" not in intern_texts
    proj_names = [p["title"] for p in tree["projects"]]
    assert "校园二手交易平台" in proj_names
    assert "校园二手" not in proj_names
    shop = next(p for p in tree["projects"] if p["title"] == "校园二手交易平台")
    shop_texts = [b["text"] for b in shop["bullets"] if not b["is_whole"]]
    assert any("7.1%→0%" in t and "一人一单" in t for t in shop_texts)
    assert "用 Redis 预扣解决超卖" not in shop_texts


def test_validate_note_payload():
    q, a, b = validate_note_payload("qa", "  缓存雪崩怎么防  ", "多级过期", "ignored")
    assert q == "缓存雪崩怎么防"
    assert a == "多级过期"
    assert b == ""
    _, _, body = validate_note_payload("note", "x", "y", "  记得量化指标  ")
    assert body == "记得量化指标"
    try:
        validate_note_payload("qa", "  ", "", "")
        raise AssertionError("empty question should fail")
    except ValueError as exc:
        assert "问题" in str(exc)
    try:
        validate_note_payload("note", "", "", "")
        raise AssertionError("empty note should fail")
    except ValueError as exc:
        assert "注释" in str(exc)
