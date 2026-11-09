"""指标事实查询：仅取时间、状态和用量，不读取简历、回答或报告正文。"""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Answer, InterviewSession, LLMUsage, ScoreReport, User


def business_users():
    # 禁用不抹除用户的历史行为；管理员和显式测试账号排除。
    return User.is_admin == 0, User.is_test == 0


class AdminAnalyticsRepository:
    def __init__(self, db: Session):
        self.db = db

    def facts(self, start, end, as_of):
        observation_end = min(end + timedelta(days=1), as_of)
        first_answer = select(Answer.session_id, func.min(Answer.created_at).label("answered_at"))\
            .where(Answer.created_at >= start, Answer.created_at < observation_end)\
            .group_by(Answer.session_id).subquery()
        sessions = self.db.execute(select(
            InterviewSession.id, InterviewSession.user_id, InterviewSession.interview_type,
            InterviewSession.interview_mode, InterviewSession.status,
            InterviewSession.started_at, InterviewSession.finished_at, first_answer.c.answered_at,
            ScoreReport.generation_status.label("report_status"), ScoreReport.created_at.label("report_at"),
        ).join(User, User.id == InterviewSession.user_id)
            .outerjoin(first_answer, first_answer.c.session_id == InterviewSession.id)
            .outerjoin(ScoreReport, ScoreReport.session_id == InterviewSession.id)
            .where(*business_users(), InterviewSession.started_at >= start, InterviewSession.started_at < end)).all()
        users = self.db.execute(select(User.id, User.created_at)
            .where(*business_users(), User.created_at >= start, User.created_at < end)).all()
        activity = self.db.execute(select(InterviewSession.user_id, Answer.session_id, Answer.created_at)
            .join(InterviewSession, InterviewSession.id == Answer.session_id)
            .join(User, User.id == InterviewSession.user_id)
            .where(*business_users(), Answer.created_at >= start, Answer.created_at < end)).all()
        usage = self.db.execute(select(
            LLMUsage.session_id, LLMUsage.created_at, LLMUsage.provider, LLMUsage.model,
            LLMUsage.cost_yuan, LLMUsage.input_tokens, LLMUsage.output_tokens,
        ).join(User, User.id == LLMUsage.user_id).where(
            *business_users(), LLMUsage.used_platform_key == 1,
            LLMUsage.created_at >= start, LLMUsage.created_at < observation_end)).all()
        return users, sessions, activity, usage

    def retention(self, start, end, as_of):
        first = select(InterviewSession.user_id.label("user_id"), func.min(Answer.created_at).label("first_at"))\
            .join(Answer, Answer.session_id == InterviewSession.id)\
            .join(User, User.id == InterviewSession.user_id).where(*business_users())\
            .group_by(InterviewSession.user_id).subquery()
        cohort = select(first).where(first.c.first_at >= start, first.c.first_at < end).subquery()
        users = self.db.execute(select(cohort)).all()
        activity = self.db.execute(select(InterviewSession.user_id, Answer.created_at)
            .join(InterviewSession, InterviewSession.id == Answer.session_id)
            .join(cohort, cohort.c.user_id == InterviewSession.user_id)
            .where(Answer.created_at >= start, Answer.created_at < min(end + timedelta(days=7), as_of))).all()
        return users, activity
