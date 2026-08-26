from dataclasses import asdict, dataclass, field


@dataclass
class PerQuestion:
    parent_id: str | None = None
    followups_so_far: int = 0
    score: float | None = None
    strengths: list = field(default_factory=list)
    weaknesses: list = field(default_factory=list)
    answers: list = field(default_factory=list)
    summary: str | None = None
    # 主问/追问拆轮：每轮独立题干、参考答案与评分（供报告拆条）
    turns: list = field(default_factory=list)
    pending_asked_text: str = ""
    pending_reference_answer: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class InterviewState:
    session_id: int
    resume_raw: str
    profile: dict
    stage: str = "INTRO"  # INTRO | ASKING | ASK_BACK | FINISHED
    plan: list = field(default_factory=list)  # [PlannedQuestion dict]
    cursor: int = 0
    history: list = field(default_factory=list)  # [{role: interviewer|candidate, text}]
    per_question: dict = field(default_factory=dict)  # qid -> PerQuestion dict
    rounds_used: int = 0
    total_rounds: int = 8
    intro_text: str = ""
    target_role: str = ""  # 目标岗位（JD 方向）
    target_company: str = ""  # 目标企业
    practice_focus: str = ""  # 本场可选定向（用户主动开启，不跨场记忆）
    skip_coding: bool = False
    review_mode: bool = False
    avoid_topics: list = field(default_factory=list)  # 去重：历史主题/题干摘要
    project_chains: list = field(default_factory=list)  # 拷打链（面试规划师生成）
    retrieved_material: str = ""  # 检索命中的相关题（注入规划官/追问官）
    create_timings: dict = field(default_factory=dict)  # 创建会话各阶段耗时（秒）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InterviewState":
        return cls(
            session_id=d["session_id"],
            resume_raw=d["resume_raw"],
            profile=d["profile"],
            stage=d.get("stage", "INTRO"),
            plan=d.get("plan", []),
            cursor=d.get("cursor", 0),
            history=d.get("history", []),
            per_question=d.get("per_question", {}),
            rounds_used=d.get("rounds_used", 0),
            total_rounds=d.get("total_rounds", 8),
            intro_text=d.get("intro_text", ""),
            target_role=d.get("target_role", ""),
            target_company=d.get("target_company", ""),
            practice_focus=d.get("practice_focus", ""),
            skip_coding=bool(d.get("skip_coding", False)),
            review_mode=bool(d.get("review_mode", False)),
            avoid_topics=list(d.get("avoid_topics") or []),
            project_chains=list(d.get("project_chains") or []),
            retrieved_material=str(d.get("retrieved_material") or ""),
            create_timings=dict(d.get("create_timings") or {}),
        )
