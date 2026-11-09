"""运营接口的请求 DTO；分页沿用管理端的 limit / offset 协议。"""
from datetime import date, datetime, timezone
from typing import Annotated, Generic, Literal, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.auth import Password

BUSINESS_TZ = ZoneInfo("Asia/Shanghai")
MAX_DATABASE_ID = 2**63 - 1
T = TypeVar("T")


class PageQuery(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class AnalyticsQuery(BaseModel):
    days: int = Field(default=7, ge=1, le=90)
    start_date: date | None = None
    end_date: date | None = None


class PageResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class AdminUserItem(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_test: bool
    is_disabled: bool
    platform_quota: int
    uses_platform_key: bool
    has_own_key: bool
    interview_count: int
    platform_cost_yuan: float
    last_active_at: datetime | None
    created_at: datetime


class AdminSessionItem(BaseModel):
    id: int
    user_id: int
    username: str
    status: str
    mode: str
    type: str
    target_role: str
    target_company: str
    started_at: datetime
    finished_at: datetime | None
    question_count: int
    answer_count: int
    rounds_used: int
    billing_source: str
    quota_state: str
    llm_calls: int
    cost_yuan: float


class AdminMessageItem(BaseModel):
    id: str
    question_id: int
    q_index: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime | None


class AdminLogItem(BaseModel):
    id: int
    level: str
    source: str
    path: str
    message: str
    detail: str
    user_id: int | None
    created_at: datetime


class AdminUsageItem(BaseModel):
    id: int
    user_id: int
    session_id: int | None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_yuan: float
    created_at: datetime


class PlatformUsageResponse(PageResponse[AdminUsageItem]):
    total_cost_yuan: float


class TimeRangeQuery(PageQuery):
    start_time: datetime | None = None
    end_time: datetime | None = None
    end_exclusive: bool = False
    business_only: bool = False

    @field_validator("start_time", "end_time")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        # 数据库存 UTC；无偏移的运营查询时间按北京时间解释。
        if value is None:
            return None
        return value.replace(tzinfo=value.tzinfo or BUSINESS_TZ).astimezone(timezone.utc).replace(tzinfo=None)

    @model_validator(mode="after")
    def valid_range(self):
        if self.start_time and self.end_time and self.start_time > self.end_time:
            raise ValueError("start_time 不能晚于 end_time")
        return self


class UserQuery(PageQuery):
    q: str = Field(default="", max_length=128)
    status: Literal["", "active", "disabled", "admin"] = ""


class LogQuery(TimeRangeQuery):
    level: Literal["", "error", "warning", "info", "debug", "critical"] = ""
    source: str = Field(default="", max_length=64)
    user_id: int | None = Field(default=None, gt=0, le=MAX_DATABASE_ID)
    q: str = Field(default="", max_length=256)


class UsageQuery(TimeRangeQuery):
    user_id: int | None = Field(default=None, gt=0, le=MAX_DATABASE_ID)
    session_id: int | None = Field(default=None, gt=0, le=MAX_DATABASE_ID)
    model: str = Field(default="", max_length=64)
    provider: str = Field(default="", max_length=32)


class SessionQuery(TimeRangeQuery):
    session_id: int | None = Field(default=None, gt=0, le=MAX_DATABASE_ID)
    user_id: int | None = Field(default=None, gt=0, le=MAX_DATABASE_ID)
    username: str = Field(default="", max_length=64)
    status: Literal["", "created", "creating", "active", "finished", "failed", "abandoned"] = ""
    mode: Literal["", "full", "specialized"] = ""
    type: Literal["", "full", "ba_gu", "project", "hr"] = ""
    target_role: str = Field(default="", max_length=128)
    target_company: str = Field(default="", max_length=128)


class MessageQuery(PageQuery):
    role: Literal["", "user", "assistant"] = ""


class ReviewQuery(PageQuery):
    status: Literal["", "pending", "resolved", "dismissed"] = "pending"
    lane: str = Field(default="", max_length=32)


class MutationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuotaGrantBody(MutationBody):
    delta: Annotated[int, Field(ge=-1_000_000, le=1_000_000)]
    note: str = Field(default="", max_length=256)


class UserUpdateBody(MutationBody):
    is_disabled: bool | None = None
    is_admin: bool | None = None
    is_test: bool | None = None
    platform_quota: int | None = Field(default=None, ge=0, le=1_000_000)


class ResetPasswordBody(MutationBody):
    new_password: Password


class TagMismatchResolveBody(MutationBody):
    status: Literal["resolved", "dismissed"]
    note: str = Field(default="", max_length=512)


class TagMismatchApplyBody(MutationBody):
    action: Literal["update", "delete"]
    roles: list[str] = Field(default_factory=list, max_length=200)
    business_scene: list[str] = Field(default_factory=list, max_length=200)
    tech_scene: list[str] = Field(default_factory=list, max_length=200)
    company: str | None = None
    category: Literal["bagu", "project"] | None = None
    note: str = Field(default="", max_length=512)
