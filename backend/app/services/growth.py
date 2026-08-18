"""用户成长档案：从历史报告聚合。

原则：
- 产出复盘档案与「可选」开练建议
- 不自动写入下一场面试记忆；practice_focus 仅在用户主动开练时由本场请求带入
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any


DIM_ORDER = ["技术深度", "项目经验", "沟通表达", "综合素质"]

# 短板 → 可训练标签（规则归类，稳定可测）
TAG_RULES: list[tuple[str, tuple[str, ...], str, str]] = [
    # tag, keywords, interview_type, focus_template
    (
        "缓存与一致性",
        ("缓存", "redis", "一致性", "穿透", "雪崩", "击穿", "canal"),
        "ba_gu",
        "本场请重点考察缓存架构与数据一致性（穿透/击穿/雪崩、多级缓存、失效策略），结合简历技术栈追问",
    ),
    (
        "并发与性能",
        ("并发", "高并发", "性能", "吞吐", "延迟", "锁", "线程", "异步"),
        "ba_gu",
        "本场请重点考察高并发与性能优化（锁、异步、限流降级、压测与瓶颈定位）",
    ),
    (
        "分布式与中间件",
        ("分布式", "消息队列", "kafka", "mq", "微服务", "rpc", "服务治理"),
        "ba_gu",
        "本场请重点考察分布式与中间件实践（一致性、投递语义、故障与降级）",
    ),
    (
        "数据库与存储",
        ("mysql", "数据库", "索引", "事务", "sql", "存储", "分库"),
        "ba_gu",
        "本场请重点考察数据库与存储（索引、事务隔离、慢查、分库分表取舍）",
    ),
    (
        "项目深度与量化",
        ("项目", "业务", "落地", "指标", "量化", "ownership", "负责", "收益", "baseline"),
        "project",
        "本场请重点深挖项目：目标/baseline/指标/失败复盘/个人贡献，要求用数据说话",
    ),
    (
        "算法与编码",
        ("算法", "代码", "复杂度", "边界", "判题", "leetcode", "手撕"),
        "ba_gu",
        "本场请加强算法与编码考察：思路、复杂度、边界与正确性，必要时插入编码题",
    ),
    (
        "表达与结构化",
        ("表达", "逻辑", "结构", "star", "条理", "沟通", "叙述", "冗长", "跳跃"),
        "hr",
        "本场请重点考察表达结构化（STAR）、条理与重点取舍，对含糊表述追问澄清",
    ),
    (
        "行为与软技能",
        ("抗压", "职业规划", "团队", "冲突", "协作", "软技能", "心态"),
        "hr",
        "本场请重点考察行为面：抗压、协作冲突、职业规划与自驱",
    ),
]

DIM_TO_PRACTICE = {
    "技术深度": ("ba_gu", "本场请加大技术深度拷打：原理、对比、工程取舍与边界条件"),
    "项目经验": ("project", "本场请以项目深挖为主：真实性、指标、失败与 ownership"),
    "沟通表达": ("hr", "本场请侧重表达清晰度、结构与倾听追问"),
    "综合素质": ("hr", "本场请侧重综合素质与行为面场景题"),
}


def _overall(dims: dict[str, Any]) -> float | None:
    vals = [float(v) for v in dims.values() if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def _norm_weak(text: str) -> str:
    t = re.sub(r"\s+", "", str(text).strip())
    return t[:28] if len(t) > 28 else t


def _tag_of(text: str) -> str | None:
    low = str(text).lower()
    for tag, kws, _itype, _focus in TAG_RULES:
        if any(k.lower() in low for k in kws):
            return tag
    return None


def _recency_weights(n: int) -> list[float]:
    """越近权重越大：末场权重大约是首场的 2^(n-1) 倍再归一。"""
    if n <= 0:
        return []
    raw = [2**i for i in range(n)]
    s = sum(raw)
    return [w / s for w in raw]


def _build_skill_tags(points: list[dict]) -> list[dict]:
    """将反复出现的弱点归为可训练标签。"""
    tag_hits: Counter[str] = Counter()
    tag_examples: dict[str, list[str]] = defaultdict(list)
    tag_sessions: dict[str, set[int]] = defaultdict(set)

    for p in points:
        sid = p.get("session_id")
        for w in p.get("weaknesses") or []:
            tag = _tag_of(w) or "其他短板"
            tag_hits[tag] += 1
            if sid is not None:
                tag_sessions[tag].add(int(sid))
            ex = str(w).strip()
            if ex and ex not in tag_examples[tag] and len(tag_examples[tag]) < 3:
                tag_examples[tag].append(ex[:60])

    meta = {t[0]: (t[2], t[3]) for t in TAG_RULES}
    out: list[dict] = []
    for tag, count in tag_hits.most_common(10):
        if count < 1:
            continue
        # 单场也展示；多场优先
        itype, focus = meta.get(tag, ("full", f"本场请针对「{tag}」相关薄弱点加强考察"))
        if itype == "full":
            mode, itype_out = "full", "full"
        else:
            mode, itype_out = "specialized", itype
        out.append(
            {
                "tag": tag,
                "count": count,
                "session_count": len(tag_sessions.get(tag, set())),
                "examples": tag_examples.get(tag, []),
                "interview_mode": mode,
                "interview_type": itype_out,
                "practice_focus": focus,
            }
        )
    return out


def _build_practice_suggestions(
    points: list[dict],
    skill_tags: list[dict],
    dim_progress: list[dict],
    recency_dims: dict[str, float | None],
) -> list[dict]:
    """可选开练建议：用户确认后才开新场，不自动进面试记忆。"""
    suggestions: list[dict] = []
    seen: set[str] = set()

    # 1) 标签化短板（优先出现 ≥2 次或最近一场）
    for t in skill_tags:
        if t["tag"] == "其他短板" and t["count"] < 2:
            continue
        key = f"tag:{t['tag']}"
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(
            {
                "id": key,
                "kind": "skill_tag",
                "title": f"补强：{t['tag']}",
                "reason": f"相关短板出现 {t['count']} 次（覆盖 {t['session_count']} 场）",
                "interview_mode": t["interview_mode"],
                "interview_type": t["interview_type"],
                "practice_focus": t["practice_focus"],
                "priority": 100 + t["count"] * 10 + t["session_count"],
            }
        )

    # 2) 近因加权最低维度
    if recency_dims:
        lowest = sorted(
            [(k, v) for k, v in recency_dims.items() if v is not None],
            key=lambda x: x[1],
        )
        if lowest:
            dim, score = lowest[0]
            itype, focus = DIM_TO_PRACTICE.get(
                dim, ("full", f"本场请针对「{dim}」偏弱表现加强考察")
            )
            mode = "full" if itype == "full" else "specialized"
            key = f"dim:{dim}"
            if key not in seen and score is not None and score < 7:
                seen.add(key)
                suggestions.append(
                    {
                        "id": key,
                        "kind": "dimension",
                        "title": f"拉升维度：{dim}",
                        "reason": f"近因加权得分约 {score:.1f}/10，相对偏弱",
                        "interview_mode": mode,
                        "interview_type": itype,
                        "practice_focus": focus,
                        "priority": 80 + (7 - float(score)) * 5,
                    }
                )

    # 3) 最近一场相对回落
    if len(points) >= 2:
        prev, cur = points[-2], points[-1]
        for dim in DIM_ORDER:
            a = (prev.get("dimensions") or {}).get(dim)
            b = (cur.get("dimensions") or {}).get(dim)
            if a is None or b is None:
                continue
            if float(b) - float(a) <= -1.0:
                itype, focus = DIM_TO_PRACTICE.get(dim, ("full", f"巩固「{dim}」"))
                mode = "full" if itype == "full" else "specialized"
                key = f"drop:{dim}"
                if key not in seen:
                    seen.add(key)
                    suggestions.append(
                        {
                            "id": key,
                            "kind": "regression",
                            "title": f"回稳：{dim}",
                            "reason": f"最近一场较上一场回落 {float(a) - float(b):.1f} 分",
                            "interview_mode": mode,
                            "interview_type": itype,
                            "practice_focus": focus,
                            "priority": 70,
                        }
                    )

    # 4) 默认：再来一场独立全流程
    if "default:full" not in seen:
        suggestions.append(
            {
                "id": "default:full",
                "kind": "default",
                "title": "再来一场独立全流程",
                "reason": "保持主路径：每场完整模拟，不依赖历史记忆",
                "interview_mode": "full",
                "interview_type": "full",
                "practice_focus": "",
                "priority": 1,
            }
        )

    suggestions.sort(key=lambda x: (-float(x.get("priority") or 0), x["title"]))
    return suggestions[:6]


def build_growth_timeline(rows: list[dict]) -> dict:
    """
    rows: 按时间升序的 [{session_id, mode, type, started_at, finished_at, report}, ...]
    """
    points: list[dict] = []
    for r in rows:
        report = r.get("report") or {}
        dims = report.get("dimension_scores") or {}
        overall = _overall(dims)
        points.append(
            {
                "session_id": r["session_id"],
                "mode": r.get("mode"),
                "type": r.get("type"),
                "target_role": r.get("target_role") or "",
                "started_at": r.get("started_at"),
                "finished_at": r.get("finished_at"),
                "overall": overall,
                "dimensions": {k: float(dims[k]) for k in dims},
                "weaknesses": list(report.get("weaknesses") or [])[:6],
                "strengths": list(report.get("strengths") or [])[:6],
                "suggestions": list(report.get("suggestions") or [])[:6],
            }
        )

    comparisons: list[dict] = []
    for i in range(1, len(points)):
        prev, cur = points[i - 1], points[i]
        dim_delta: dict[str, float] = {}
        keys = set((prev.get("dimensions") or {}).keys()) | set(
            (cur.get("dimensions") or {}).keys()
        )
        for k in keys:
            a = float((prev.get("dimensions") or {}).get(k) or 0)
            b = float((cur.get("dimensions") or {}).get(k) or 0)
            dim_delta[k] = round(b - a, 2)
        o_prev = prev.get("overall")
        o_cur = cur.get("overall")
        overall_delta = None
        if o_prev is not None and o_cur is not None:
            overall_delta = round(float(o_cur) - float(o_prev), 2)
        improved = sorted(
            [k for k, v in dim_delta.items() if v > 0],
            key=lambda k: dim_delta[k],
            reverse=True,
        )
        declined = sorted(
            [k for k, v in dim_delta.items() if v < 0],
            key=lambda k: dim_delta[k],
        )
        comparisons.append(
            {
                "from_session_id": prev["session_id"],
                "to_session_id": cur["session_id"],
                "from_at": prev.get("started_at"),
                "to_at": cur.get("started_at"),
                "overall_delta": overall_delta,
                "dimension_delta": dim_delta,
                "improved": improved,
                "declined": declined,
                "new_gaps": list(cur.get("weaknesses") or [])[:4],
                "kept_strengths": list(cur.get("strengths") or [])[:3],
            }
        )

    weak_counter: Counter[str] = Counter()
    for p in points:
        for w in p.get("weaknesses") or []:
            key = _norm_weak(w)
            if key:
                weak_counter[key] += 1

    recurring_gaps = [
        {"text": t, "count": c}
        for t, c in weak_counter.most_common(8)
        if c >= 2 or len(points) == 1
    ]

    dim_progress: list[dict] = []
    if len(points) >= 1:
        first = points[0].get("dimensions") or {}
        last = points[-1].get("dimensions") or {}
        for k in DIM_ORDER:
            if k not in first and k not in last:
                continue
            a = float(first.get(k) or 0)
            b = float(last.get(k) or 0)
            dim_progress.append(
                {
                    "dimension": k,
                    "first": a if k in first else None,
                    "latest": b if k in last else None,
                    "delta": round(b - a, 2) if k in first and k in last else None,
                }
            )
        for k in set(first) | set(last):
            if k in DIM_ORDER:
                continue
            a = float(first.get(k) or 0)
            b = float(last.get(k) or 0)
            dim_progress.append(
                {
                    "dimension": k,
                    "first": a if k in first else None,
                    "latest": b if k in last else None,
                    "delta": round(b - a, 2) if k in first and k in last else None,
                }
            )

    # 近因加权能力画像
    window = points[-5:] if points else []
    weights = _recency_weights(len(window))
    recency_dims: dict[str, float | None] = {}
    for dim in DIM_ORDER:
        acc = 0.0
        wsum = 0.0
        for p, w in zip(window, weights):
            v = (p.get("dimensions") or {}).get(dim)
            if v is None:
                continue
            acc += float(v) * w
            wsum += w
        recency_dims[dim] = round(acc / wsum, 2) if wsum > 0 else None

    recency_vals = [v for v in recency_dims.values() if v is not None]
    readiness = round(sum(recency_vals) / len(recency_vals) * 10, 1) if recency_vals else None

    skill_tags = _build_skill_tags(points)
    practice_suggestions = _build_practice_suggestions(
        points, skill_tags, dim_progress, recency_dims
    )

    first_overall = points[0].get("overall") if points else None
    latest_overall = points[-1].get("overall") if points else None
    total_delta = None
    if first_overall is not None and latest_overall is not None:
        total_delta = round(float(latest_overall) - float(first_overall), 2)

    roles = [p.get("target_role") for p in points if p.get("target_role")]
    primary_role = roles[-1] if roles else ""

    return {
        "session_count": len(points),
        "points": points,
        "comparisons": comparisons,
        "recurring_gaps": recurring_gaps,
        "dimension_progress": dim_progress,
        "recency_dimensions": recency_dims,
        "skill_tags": skill_tags,
        "practice_suggestions": practice_suggestions,
        "summary": {
            "first_overall": first_overall,
            "latest_overall": latest_overall,
            "total_delta": total_delta,
            "readiness": readiness,
            "primary_role": primary_role,
            "trend": (
                "up"
                if total_delta is not None and total_delta > 0.2
                else "down"
                if total_delta is not None and total_delta < -0.2
                else "flat"
                if total_delta is not None
                else "insufficient"
            ),
        },
    }


def build_growth_insight(payload: dict) -> dict:
    """可选：用 LLM 生成一段成长解读（不进入面试记忆）。"""
    from app.services.llm.client import OpenAiLlm

    system = """你是面试成长教练。根据用户多次模拟面试的量化数据，写简洁中文成长解读。
只输出 JSON：
{
  "headline": "一句话总评",
  "progress": ["进步点1", "..."],
  "gaps": ["仍需加强1", "..."],
  "next_focus": ["可选的下一场练习方向1", "..."]
}
注意：主产品是「每场独立模拟面试」；next_focus 只是可选建议，不要写成必须依赖历史记忆。
不要编造数据中没有的分数或场次。"""
    user = json.dumps(
        {
            "summary": payload.get("summary"),
            "dimension_progress": payload.get("dimension_progress"),
            "recency_dimensions": payload.get("recency_dimensions"),
            "skill_tags": payload.get("skill_tags"),
            "practice_suggestions": payload.get("practice_suggestions"),
            "recurring_gaps": payload.get("recurring_gaps"),
            "recent_comparisons": (payload.get("comparisons") or [])[-3:],
            "recent_points": [
                {
                    "session_id": p.get("session_id"),
                    "overall": p.get("overall"),
                    "dimensions": p.get("dimensions"),
                    "weaknesses": p.get("weaknesses"),
                }
                for p in (payload.get("points") or [])[-5:]
            ],
        },
        ensure_ascii=False,
    )
    data = OpenAiLlm().chat_json(system, user)
    return {
        "headline": str(data.get("headline") or ""),
        "progress": list(data.get("progress") or [])[:6],
        "gaps": list(data.get("gaps") or [])[:6],
        "next_focus": list(data.get("next_focus") or [])[:6],
    }
