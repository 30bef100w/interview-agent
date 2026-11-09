"""完整业务日、同长度上期和固定观察窗的运营指标。"""
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.repositories.admin_analytics import AdminAnalyticsRepository
from app.schemas.admin import AnalyticsQuery, BUSINESS_TZ


def local_date(utc_naive):
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TZ).date()


def utc_midnight(day):
    return datetime.combine(day, time.min, BUSINESS_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def ratio(numerator, denominator):
    return round(numerator / denominator, 6) if denominator else None


def comparison(current, previous, unit):
    if current is None or previous is None:
        return {"kind": "unavailable", "value": None}
    if unit == "ratio":
        return {"kind": "pp", "value": round((current - previous) * 100, 2)}
    if previous == 0:
        return {"kind": "unchanged" if current == 0 else "new", "value": 0 if current == 0 else None}
    return {"kind": "percent", "value": round((current - previous) / abs(previous) * 100, 2)}


class AdminAnalyticsService:
    def __init__(self, db: Session):
        self.repo = AdminAnalyticsRepository(db)

    def overview(self, query: AnalyticsQuery, *, now=None):
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        as_of = now.replace(tzinfo=None)
        today = now.astimezone(BUSINESS_TZ).date()
        last_day = query.end_date or today - timedelta(days=1)
        first_day = query.start_date or last_day - timedelta(days=query.days - 1)
        days = (last_day - first_day).days + 1
        if not 1 <= days <= 90 or last_day >= today:
            raise HTTPException(422, "请选择 1–90 个已结束的完整日期，最晚为北京时间昨天")
        start, end = utc_midnight(first_day), utc_midnight(last_day + timedelta(days=1))
        previous_start = start - timedelta(days=days)
        facts = self.repo.facts(previous_start, end, as_of)
        current = self.summarize(facts, start, end, as_of)
        previous = self.summarize(facts, previous_start, start, as_of)
        specs = [
            ("new_users", "新增用户", "count", "up", "区间内注册的业务用户，排除管理员及测试账号。"),
            ("answer_users", "已答题用户", "count", "up", "区间内有持久化回答的去重用户；不以登录代替答题。"),
            ("answered_sessions", "已答题面试", "count", "up", "区间内产生过回答的去重面试；可能包含此前创建的会话。"),
            ("completion_rate", "24h 面试完成率", "ratio", "up", "区间内创建且已观察满 24h 的会话，在创建后 24h 内完成的比例。"),
            ("report_rate", "24h 正常报告率", "ratio", "up", "24h 内完成的会话中，24h 内交付正常终评报告的比例；存在未知结果时暂不计算。"),
            ("cost_per_session", "场均平台成本 · 24h", "yuan", "down", "同一成熟会话群创建后 24h 内已记录的平台估算成本 / 会话数；包含失败和退出场次。"),
        ]
        metrics = [{"key": key, "label": label, "unit": unit, "better": better,
                    "current": current["values"][key], "previous": previous["values"][key],
                    "change": comparison(current["values"][key], previous["values"][key], unit),
                    "definition": definition} for key, label, unit, better, definition in specs]
        types = []
        for key in current["types"].keys() | previous["types"].keys():
            cur = current["types"].get(key, self.type_bucket())
            prev = previous["types"].get(key, self.type_bucket())
            types.append({"type": key[0], "mode": key[1], **cur,
                          "previous_created": prev["created"], "delta": cur["created"] - prev["created"],
                          "completion_rate": ratio(cur["completed"], cur["mature"]),
                          "abandon_rate": ratio(cur["abandoned"], cur["mature"])})
        types.sort(key=lambda item: (-item["created"], item["mode"], item["type"]))
        insights = self.insights(current, previous, types)
        return {
            "period": {"start_date": str(first_day), "end_date": str(last_day), "days": days,
                       "previous_start_date": str(first_day - timedelta(days=days)),
                       "previous_end_date": str(first_day - timedelta(days=1)),
                       "start_time": start.isoformat() + "Z", "end_time": end.isoformat() + "Z"},
            "timezone": "Asia/Shanghai", "as_of": now.isoformat(), "observation_hours": 24,
            "metrics": metrics, "trend": current["trend"], "previous_trend": previous["trend"],
            "funnel": current["funnel"], "quality": current["quality"], "types": types,
            "cost": current["cost"], "retention": self.retention(start, end, as_of, today),
            "insights": insights,
        }

    @staticmethod
    def type_bucket():
        return {"created": 0, "mature": 0, "answered": 0, "completed": 0, "abandoned": 0, "failed": 0}

    def summarize(self, facts, start, end, as_of):
        users, sessions, activity, usage = facts
        trend = {}
        for index in range((end - start).days):
            day = str(local_date(start + timedelta(days=index)))
            trend[day] = {"date": day, "new_users": 0, "created_sessions": 0,
                          "answer_users": set(), "answered_sessions": set(), "platform_cost_yuan": 0.0}
        for row in users:
            if start <= row.created_at < end:
                trend[str(local_date(row.created_at))]["new_users"] += 1
        answer_users, answered_sessions = set(), set()
        for row in activity:
            if start <= row.created_at < end:
                day = trend[str(local_date(row.created_at))]
                day["answer_users"].add(row.user_id)
                day["answered_sessions"].add(row.session_id)
                answer_users.add(row.user_id)
                answered_sessions.add(row.session_id)
        selected = [s for s in sessions if start <= s.started_at < end]
        mature = {s.id: s for s in selected if s.started_at + timedelta(days=1) <= as_of}
        types = defaultdict(self.type_bucket)
        answered = completed = funnel_completed = success = fallback = unknown = funnel_success = 0
        for row in selected:
            trend[str(local_date(row.started_at))]["created_sessions"] += 1
            bucket = types[(row.interview_type, row.interview_mode)]
            bucket["created"] += 1
            status = (row.status or "").lower()
            # 没有独立失败时间，只统计当前失败状态，包含尚未成熟的会话。
            bucket["failed"] += int(status == "failed")
            if row.id not in mature:
                continue
            cutoff = row.started_at + timedelta(days=1)
            bucket["mature"] += 1
            has_answer = row.answered_at is not None and row.started_at <= row.answered_at < cutoff
            answered += int(has_answer)
            bucket["answered"] += int(has_answer)
            ended = row.finished_at is not None and row.started_at <= row.finished_at < cutoff
            done = status == "finished" and ended
            completed += int(done)
            bucket["completed"] += int(done)
            bucket["abandoned"] += int(status == "abandoned" and ended)
            funnel_completed += int(done and has_answer)
            if done:
                report_in_time = row.report_at is not None and row.started_at <= row.report_at < cutoff
                report_status = row.report_status if report_in_time else "unknown"
                success += int(report_status == "success")
                fallback += int(report_status == "fallback")
                unknown += int(report_status not in {"success", "fallback"})
                funnel_success += int(report_status == "success" and has_answer)
        models = {}
        total_cost = unassigned_cost = cohort_cost = 0.0
        covered_sessions = set()
        for row in usage:
            if start <= row.created_at < end:
                key = (row.provider, row.model)
                model = models.setdefault(key, {"provider": row.provider, "model": row.model,
                    "records": 0, "input_tokens": 0, "output_tokens": 0, "cost_yuan": 0.0})
                model["records"] += 1
                model["input_tokens"] += row.input_tokens or 0
                model["output_tokens"] += row.output_tokens or 0
                model["cost_yuan"] += row.cost_yuan or 0
                total_cost += row.cost_yuan or 0
                if row.session_id is None:
                    unassigned_cost += row.cost_yuan or 0
                trend[str(local_date(row.created_at))]["platform_cost_yuan"] += row.cost_yuan or 0
            session = mature.get(row.session_id)
            if session and session.started_at <= row.created_at < session.started_at + timedelta(days=1):
                cohort_cost += row.cost_yuan or 0
                covered_sessions.add(session.id)
        for row in trend.values():
            row["answer_users"] = len(row["answer_users"])
            row["answered_sessions"] = len(row["answered_sessions"])
            row["platform_cost_yuan"] = round(row["platform_cost_yuan"], 6)
        for row in models.values():
            row["cost_yuan"] = round(row["cost_yuan"], 6)
            row["share"] = ratio(row["cost_yuan"], total_cost)
        funnel = [{"key": "created", "label": "创建面试", "count": len(mature)},
                  {"key": "answered", "label": "产生回答", "count": answered},
                  {"key": "completed", "label": "完成面试", "count": funnel_completed},
                  {"key": "report", "label": "正常报告", "count": funnel_success}]
        for index, step in enumerate(funnel):
            step["conversion"] = ratio(step["count"], funnel[index - 1]["count"]) if index else None
            step["lost"] = funnel[index - 1]["count"] - step["count"] if index else 0
        return {
            "values": {"new_users": sum(r["new_users"] for r in trend.values()),
                "answer_users": len(answer_users), "answered_sessions": len(answered_sessions),
                "completion_rate": ratio(completed, len(mature)),
                "report_rate": ratio(success, completed) if not unknown else None,
                "cost_per_session": round(cohort_cost / len(mature), 6) if mature and covered_sessions else None},
            "trend": list(trend.values()), "types": types, "funnel": funnel,
            "quality": {"created": len(selected), "mature": len(mature), "pending": len(selected) - len(mature),
                        "completed": completed, "report_success": success, "report_fallback": fallback,
                        "report_unknown": unknown, "cost_recorded_sessions": len(covered_sessions)},
            "cost": {"total_yuan": round(total_cost, 6), "unassigned_yuan": round(unassigned_cost, 6),
                     "models": sorted(models.values(), key=lambda row: (-row["cost_yuan"], row["provider"], row["model"]))},
        }

    def retention(self, start, end, as_of, today):
        users, activity = self.repo.retention(start, end, as_of)
        active_days = defaultdict(set)
        for row in activity:
            active_days[row.user_id].add(local_date(row.created_at))
        result = []
        for offset in (1, 7):
            eligible = [u for u in users if local_date(u.first_at) + timedelta(days=offset) < today]
            retained = sum(local_date(u.first_at) + timedelta(days=offset) in active_days[u.user_id] for u in eligible)
            result.append({"day": offset, "eligible": len(eligible), "retained": retained,
                           "pending": len(users) - len(eligible), "rate": ratio(retained, len(eligible))})
        return result

    @staticmethod
    def insights(current, previous, types):
        quality = current["quality"]
        result = []
        if not quality["created"] and not current["values"]["answer_users"]:
            result.append({"tone": "neutral", "text": "当前区间还没有业务面试或答题记录，暂时无法判断使用趋势。"})
        if quality["pending"]:
            result.append({"tone": "neutral", "text": f"{quality['pending']} 场面试尚未观察满 24h，暂不纳入完成率和漏斗。"})
        if quality["report_fallback"]:
            result.append({"tone": "warning", "text": f"24h 内完成的面试中有 {quality['report_fallback']} 场使用兜底终评，建议检查终评节点。"})
        if quality["report_unknown"]:
            result.append({"tone": "warning", "text": f"{quality['report_unknown']} 场已完成面试的报告结果未知，正常报告率暂不计算。"})
        changed = sorted((row for row in types if row["delta"]), key=lambda row: -abs(row["delta"]))
        if changed:
            row = changed[0]
            names = {"full": "全流程", "ba_gu": "八股专项", "project": "项目专项", "hr": "HR 专项"}
            result.append({"tone": "neutral", "text": f"创建量变化最大的类型为{names.get(row['type'], row['type'])}：本期 {row['created']} 场，上期 {row['previous_created']} 场，变化 {row['delta']:+d} 场。"})
        models = current["cost"]["models"]
        if models and current["cost"]["total_yuan"] > 0:
            model = models[0]
            result.append({"tone": "neutral", "text": f"平台估算成本最高的模型为 {model['model']}，占本期已记录成本的 {model['share']:.1%}。"})
        return result
