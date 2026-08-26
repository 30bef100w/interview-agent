"""成长档案聚合单测：标签化短板 + 开练建议。"""
from app.services.growth import build_growth_timeline


def _row(sid: int, dims: dict, weaknesses: list[str], role: str = ""):
    return {
        "session_id": sid,
        "mode": "full",
        "type": "full",
        "target_role": role,
        "started_at": f"2026-01-0{sid}T10:00:00",
        "finished_at": f"2026-01-0{sid}T11:00:00",
        "report": {
            "dimension_scores": dims,
            "weaknesses": weaknesses,
            "strengths": [],
            "suggestions": [],
        },
    }


def test_growth_builds_tags_and_suggestions():
    rows = [
        _row(
            1,
            {"技术深度": 5, "项目经验": 6, "沟通表达": 7, "综合素质": 6},
            ["Redis 缓存一致性讲不清", "项目缺少量化指标"],
        ),
        _row(
            2,
            {"技术深度": 4, "项目经验": 7, "沟通表达": 7, "综合素质": 6},
            ["缓存穿透与雪崩未覆盖", "表达结构一般"],
            role="后端开发",
        ),
    ]
    data = build_growth_timeline(rows)
    assert data["session_count"] == 2
    assert data["summary"]["readiness"] is not None
    assert data["recency_dimensions"]["技术深度"] is not None
    tags = {t["tag"] for t in data["skill_tags"]}
    assert "缓存与一致性" in tags
    assert any(s["kind"] == "skill_tag" for s in data["practice_suggestions"])
    assert any(s["id"] == "default:full" for s in data["practice_suggestions"])
    focus_items = [s for s in data["practice_suggestions"] if s.get("practice_focus")]
    assert focus_items
    assert focus_items[0]["interview_mode"] in ("full", "specialized")


def test_growth_weekly_and_milestones():
    rows = [
        _row(1, {"技术深度": 6, "项目经验": 6, "沟通表达": 6, "综合素质": 6}, ["缓存"]),
        _row(2, {"技术深度": 7, "项目经验": 7, "沟通表达": 7, "综合素质": 7}, ["表达"]),
    ]
    data = build_growth_timeline(rows)
    assert data.get("weekly_stats") is not None
    assert data.get("milestones")
    assert data.get("focus_dimension")
