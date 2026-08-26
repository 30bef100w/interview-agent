from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    resume_id: int
    interview_mode: str = Field(pattern="^(full|specialized)$")  # 全流程混合 | 专项专场
    interview_type: str = Field(pattern="^(full|ba_gu|project|hr)$")
    question_count: int = Field(default=8, ge=4, le=20)  # 总轮次上限
    # 目标岗位 / 企业：开练时写入，引擎规划与提问会消费
    target_role: str = Field(default="", max_length=128)
    target_company: str = Field(default="", max_length=128)
    # 本场可选定向焦点（来自成长档案建议）；只影响本场规划，不跨场记忆
    practice_focus: str = Field(default="", max_length=500)
    # 自定义设置
    skip_coding: bool = False  # 全流程下去掉算法环节
    dedup_scope: str = Field(default="all", pattern="^(none|last5|last10|all)$")
    review_mode: bool = False  # 按成长档案短板复习


class SessionOut(BaseModel):
    session_id: int
    status: str
    stage: str = ""
    message: str = ""
    # 开练自定义设置回显，便于确认是否生效
    settings_applied: dict | None = None


class CreateProgressOut(BaseModel):
    status: str  # creating | ready | failed
    progress: int = 0
    label: str = ""
    step: str = ""
    settings_applied: dict | None = None


class AnswerRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class AnswerOut(BaseModel):
    message: str
    stage: str
    status: str
    finished: bool = False
    report: dict | None = None


class CodeRunRequest(BaseModel):
    slug: str
    code: str = Field(min_length=1, max_length=20000)
    language: str = Field(default="python", pattern="^(python|java|cpp|go)$")
    coding_mode: str = Field(default="function", pattern="^(function|scratch)$")


class CodeRunResponse(BaseModel):
    slug: str
    verdict: str
    passed: int = 0
    total: int = 0
    results: list[dict] = []
    message: str | None = None


class CodeSubmitRequest(BaseModel):
    slug: str
    code: str = Field(min_length=1, max_length=20000)
    language: str = Field(default="python", pattern="^(python|java|cpp|go)$")
    coding_mode: str = Field(default="function", pattern="^(function|scratch)$")


class CodeSubmitResponse(BaseModel):
    judge: dict
    review: dict
    message: str
    stage: str
    status: str
    finished: bool = False
