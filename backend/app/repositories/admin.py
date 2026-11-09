"""运营数据访问层，不承担权限判断、事务提交或 HTTP 响应。"""
from datetime import timedelta

from sqlalchemy import case, func, literal, or_, select, union_all, update
from sqlalchemy.orm import Session

from app.models import (
    Answer, InterviewSession, LLMUsage, Question, QuotaGrant, ScoreReport,
    SystemLog, TagMismatchReview, User, UserLlmSetting,
)
from app.schemas.admin import LogQuery, PageQuery, ReviewQuery, SessionQuery, UsageQuery, UserQuery


class AdminRepository:
    def __init__(self, db: Session):
        self.db = db

    def page(self, stmt, query: PageQuery) -> tuple[list, int]:
        total = self.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        return list(self.db.execute(stmt.offset(query.offset).limit(query.limit))), int(total)

    def user(self, user_id: int, *, lock: bool = False):
        stmt = select(User).where(User.id == user_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return self.db.scalar(stmt)

    def user_setting(self, user_id: int):
        return self.db.scalar(select(UserLlmSetting).where(UserLlmSetting.user_id == user_id))

    def set_quota_if_current(self, user_id: int, old: int, new: int) -> bool:
        result = self.db.execute(update(User).where(User.id == user_id, User.platform_quota == old)
            .values(platform_quota=new).execution_options(synchronize_session=False))
        return result.rowcount == 1

    def stats(self, day0, month0):
        def count_if(condition):
            return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)
        users = self.db.execute(select(func.count(User.id), count_if(User.is_disabled == 1))).one()
        def answer_users(since):
            return self.db.scalar(select(func.count(func.distinct(InterviewSession.user_id)))
                .select_from(Answer).join(InterviewSession, InterviewSession.id == Answer.session_id)
                .join(User, User.id == InterviewSession.user_id)
                .where(User.is_admin == 0, User.is_test == 0, Answer.created_at >= since,
                       Answer.created_at < day0 + timedelta(days=1))) or 0
        users = (*users, answer_users(day0), answer_users(day0 - timedelta(days=29)))
        sessions = self.db.execute(select(func.count(InterviewSession.id),
            count_if(InterviewSession.started_at >= day0), count_if(InterviewSession.started_at >= month0))).one()
        cost = self.db.scalar(select(func.coalesce(func.sum(LLMUsage.cost_yuan), 0)).where(LLMUsage.used_platform_key == 1))
        grants = self.db.scalar(select(func.coalesce(func.sum(QuotaGrant.delta), 0)).where(QuotaGrant.delta > 0))
        errors = self.db.scalar(select(func.count(SystemLog.id)).where(SystemLog.level == "error"))
        return users, sessions, cost, grants, errors

    def review_stats(self, day0):
        pending = self.db.scalar(select(func.count(TagMismatchReview.id)).where(TagMismatchReview.status == "pending"))
        today = self.db.scalar(select(func.count(TagMismatchReview.id)).where(TagMismatchReview.created_at >= day0))
        return int(pending or 0), int(today or 0)

    @staticmethod
    def time_conditions(column, query) -> list:
        conditions = []
        if query.start_time is not None:
            conditions.append(column >= query.start_time)
        if query.end_time is not None:
            conditions.append(column < query.end_time if query.end_exclusive else column <= query.end_time)
        return conditions

    def users(self, query: UserQuery):
        stmt = select(User).order_by(User.id.desc())
        keyword = query.q.strip()
        if keyword:
            match = User.username.contains(keyword, autoescape=True)
            if keyword.isdecimal() and int(keyword) <= 2**63 - 1:
                match = or_(match, User.id == int(keyword))
            stmt = stmt.where(match)
        if query.status == "active":
            stmt = stmt.where(User.is_disabled == 0)
        elif query.status == "disabled":
            stmt = stmt.where(User.is_disabled == 1)
        elif query.status == "admin":
            stmt = stmt.where(User.is_admin == 1)
        rows, total = self.page(stmt, query)
        return [row[0] for row in rows], total

    def user_summaries(self, ids: list[int]) -> tuple[dict, dict, dict]:
        if not ids:
            return {}, {}, {}
        # 三次批量查询，不随分页用户数增加查询次数。
        counts = dict(self.db.execute(select(InterviewSession.user_id, func.count())
            .where(InterviewSession.user_id.in_(ids)).group_by(InterviewSession.user_id)).all())
        costs = dict(self.db.execute(select(LLMUsage.user_id, func.sum(LLMUsage.cost_yuan))
            .where(LLMUsage.user_id.in_(ids), LLMUsage.used_platform_key == 1)
            .group_by(LLMUsage.user_id)).all())
        settings = {s.user_id: s for s in self.db.scalars(select(UserLlmSetting)
            .where(UserLlmSetting.user_id.in_(ids)))}
        return counts, costs, settings

    def recent_sessions(self, user_id: int):
        return self.db.scalars(select(InterviewSession).where(InterviewSession.user_id == user_id)
            .order_by(InterviewSession.id.desc()).limit(10)).all()

    def quota_grants(self, user_id: int):
        return self.db.scalars(select(QuotaGrant).where(QuotaGrant.user_id == user_id)
            .order_by(QuotaGrant.id.desc()).limit(20)).all()

    def logs(self, query: LogQuery):
        conditions = self.time_conditions(SystemLog.created_at, query)
        if query.level:
            conditions.append(SystemLog.level == query.level)
        if query.source.strip():
            conditions.append(SystemLog.source == query.source.strip())
        if query.user_id is not None:
            conditions.append(SystemLog.user_id == query.user_id)
        if query.q.strip():
            conditions.append(or_(SystemLog.message.contains(query.q.strip(), autoescape=True),
                                  SystemLog.path.contains(query.q.strip(), autoescape=True)))
        rows, total = self.page(select(SystemLog).where(*conditions).order_by(SystemLog.id.desc()), query)
        return [row[0] for row in rows], total

    def usage(self, query: UsageQuery):
        conditions = [LLMUsage.used_platform_key == 1, *self.time_conditions(LLMUsage.created_at, query)]
        if query.business_only:
            conditions.append(LLMUsage.user_id.in_(select(User.id).where(User.is_admin == 0, User.is_test == 0)))
        for field in ("user_id", "session_id"):
            value = getattr(query, field)
            if value is not None:
                conditions.append(getattr(LLMUsage, field) == value)
        if query.model.strip():
            conditions.append(LLMUsage.model == query.model.strip())
        if query.provider.strip():
            conditions.append(LLMUsage.provider == query.provider.strip())
        total_cost = self.db.scalar(select(func.coalesce(func.sum(LLMUsage.cost_yuan), 0)).where(*conditions))
        rows, total = self.page(select(LLMUsage).where(*conditions).order_by(LLMUsage.id.desc()), query)
        return [row[0] for row in rows], total, float(total_cost or 0)

    def sessions(self, query: SessionQuery):
        conditions = self.time_conditions(InterviewSession.started_at, query)
        if query.business_only:
            conditions.extend([User.is_admin == 0, User.is_test == 0])
        for field in ("user_id", "target_role", "target_company"):
            value = getattr(query, field)
            if value not in (None, ""):
                conditions.append(getattr(InterviewSession, field) == value)
        if query.session_id is not None:
            conditions.append(InterviewSession.id == query.session_id)
        if query.username.strip():
            conditions.append(User.username == query.username.strip())
        if query.status:
            conditions.append(func.lower(InterviewSession.status) == query.status)
        if query.mode:
            conditions.append(InterviewSession.interview_mode == query.mode)
        if query.type:
            conditions.append(InterviewSession.interview_type == query.type)
        stmt = select(InterviewSession, User.username).join(User, User.id == InterviewSession.user_id)
        return self.page(stmt.where(*conditions).order_by(InterviewSession.started_at.desc(), InterviewSession.id.desc()), query)

    def session_summaries(self, ids: list[int]) -> tuple[dict, dict, dict]:
        if not ids:
            return {}, {}, {}
        questions = dict(self.db.execute(select(Question.session_id, func.count())
            .where(Question.session_id.in_(ids)).group_by(Question.session_id)).all())
        answers = dict(self.db.execute(select(Answer.session_id, func.count())
            .where(Answer.session_id.in_(ids)).group_by(Answer.session_id)).all())
        usage = {row.session_id: row for row in self.db.execute(select(
            LLMUsage.session_id, func.count().label("calls"),
            func.sum(LLMUsage.cost_yuan).label("cost"),
        ).where(LLMUsage.session_id.in_(ids)).group_by(LLMUsage.session_id))}
        return questions, answers, usage

    def session(self, session_id: int):
        return self.db.execute(select(InterviewSession, User.username)
            .join(User, User.id == InterviewSession.user_id).where(InterviewSession.id == session_id)).first()

    def report(self, session_id: int):
        return self.db.scalar(select(ScoreReport.report_json).where(ScoreReport.session_id == session_id))

    def messages(self, session_id: int, query):
        # 问题、追问、回答按题序合并；服务端分页，避免一次加载整场长对话。
        questions = select(
            Question.id.label("id"), Question.id.label("question_id"), Question.q_index.label("q_index"),
            literal("assistant").label("role"), literal(0).label("role_order"),
            Question.text.label("content"), literal(None).label("created_at"),
        ).where(Question.session_id == session_id)
        answers = select(
            Answer.id.label("id"), Answer.question_id.label("question_id"), Question.q_index.label("q_index"),
            literal("user").label("role"), literal(1).label("role_order"),
            Answer.content.label("content"), Answer.created_at.label("created_at"),
        ).join(Question, Question.id == Answer.question_id).where(Answer.session_id == session_id)
        messages = union_all(questions, answers).subquery()
        stmt = select(messages)
        if query.role:
            stmt = stmt.where(messages.c.role == query.role)
        return self.page(stmt.order_by(messages.c.q_index, messages.c.question_id,
            messages.c.role_order, messages.c.created_at, messages.c.id), query)

    def reviews(self, query: ReviewQuery):
        stmt = select(TagMismatchReview)
        if query.status:
            stmt = stmt.where(TagMismatchReview.status == query.status)
        if query.lane.strip():
            stmt = stmt.where(TagMismatchReview.lane == query.lane.strip())
        rows, total = self.page(stmt.order_by(TagMismatchReview.id.desc()), query)
        return [row[0] for row in rows], total
