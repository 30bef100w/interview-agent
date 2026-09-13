"""飞书管家：假 LLM JSON 覆盖闲聊 / 开场 / 作答 / 暂停 / 续面。"""
from app.services.feishu_channel import ChannelSession, ChannelUser, handle_inbound
from app.services.feishu_orchestrator import FeishuOrchestrator, MemoryStore, _norm_mode_type


class QueueLlm:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.calls: list[str] = []

    def chat_json(self, system: str, user: str, **_kwargs) -> dict:
        self.calls.append(user)
        if not self.replies:
            raise AssertionError("LLM queue empty")
        return self.replies.pop(0)


class FakeRuntime:
    def __init__(self, llm: QueueLlm | None = None) -> None:
        self.user = ChannelUser(id=1, username="xuyongqi")
        self.llm = llm
        self.resume = True
        self.session: ChannelSession | None = None
        self.starts: list[dict] = []
        self.answers: list[str] = []
        self.abandoned: list[int] = []
        self.resumed: list[int] = []
        self.history: list[dict] = []

    def resolve_sender(self, open_id: str) -> ChannelUser | None:
        return self.user if open_id == "ou_me" else None

    def latest_open_session(self, user_id: int) -> ChannelSession | None:
        return self.session

    def has_resume(self, user_id: int) -> bool:
        return self.resume

    def start_session(self, user, **kwargs) -> ChannelSession:
        self.starts.append(kwargs)
        on_progress = kwargs.get("on_progress")
        if on_progress:
            on_progress("规划中")
        self.session = ChannelSession(id=7, status="active", stage="INTRO")
        return self.session

    def submit_answer(self, user, session_id: int, text: str) -> dict:
        self.answers.append(text)
        return {"message": "追问：锁粒度怎么选？", "finished": False}

    def abandon(self, user, session_id: int) -> None:
        self.abandoned.append(session_id)
        self.session = None

    def session_url(self, session_id: int) -> str:
        return f"https://deeplyask.online/interview/{session_id}"

    def llm_for(self, user: ChannelUser):
        return self.llm

    def list_resumes(self, user: ChannelUser) -> list[dict]:
        return [{"id": 11, "filename": "xuyongqi.pdf", "created_at": "2026-01-01"}]

    def list_sessions(self, user: ChannelUser, limit: int = 12) -> list[dict]:
        return list(self.history)

    def get_session(self, user: ChannelUser, session_id: int) -> dict:
        return {"id": session_id, "status": "active", "stage": "ASKING", "last_interviewer": "上一问"}

    def get_account(self, user: ChannelUser) -> dict:
        return {"has_resume": True, "resume_count": 1, "platform_quota": 2, "uses_platform_key": True}

    def resume_session(self, user: ChannelUser, session_id: int) -> dict:
        self.resumed.append(session_id)
        self.session = ChannelSession(id=session_id, status="active", stage="ASKING")
        return {
            "ok": True,
            "session_id": session_id,
            "message": "请讲 Redis 缓存击穿。",
            "url": self.session_url(session_id),
        }


def _orch(tmp_path):
    return FeishuOrchestrator(MemoryStore(tmp_path))


def test_chat_does_not_start_engine(tmp_path):
    llm = QueueLlm(
        [{"kind": "chat", "say": "开场需要简历、模式和轮次，可以说按默认。", "tool": None, "args": {}}]
    )
    rt = FakeRuntime(llm)
    out = handle_inbound(
        {"sender_id": "ou_me", "content": "深问怎么用", "message_type": "text"},
        runtime=rt,
        orchestrator=_orch(tmp_path),
    )
    assert "简历" in out[0]
    assert rt.starts == []
    assert rt.answers == []


def test_start_with_defaults(tmp_path):
    llm = QueueLlm(
        [
            {
                "kind": "tool",
                "say": "",
                "tool": "start_interview",
                "args": {"target_role": "后端", "question_count": 8},
            }
        ]
    )
    rt = FakeRuntime(llm)
    emitted = []
    out = handle_inbound(
        {"sender_id": "ou_me", "content": "用最新简历面后端", "message_type": "text"},
        runtime=rt,
        emit=emitted.append,
        orchestrator=_orch(tmp_path),
    )
    assert rt.starts
    assert rt.starts[0]["role"] == "后端"
    assert rt.starts[0]["rounds"] == 8
    assert rt.starts[0]["interview_mode"] == "full"
    assert any("规划" in x for x in emitted)
    assert "自我介绍" in out[0]


def test_forward_answer_while_interviewing(tmp_path):
    orch = _orch(tmp_path)
    llm = QueueLlm(
        [
            {"kind": "tool", "say": "", "tool": "start_interview", "args": {"target_role": "后端"}},
            {"kind": "forward_answer", "say": "", "tool": None, "args": {}},
        ]
    )
    rt = FakeRuntime(llm)
    handle_inbound(
        {"sender_id": "ou_me", "content": "开场", "message_type": "text"},
        runtime=rt,
        emit=lambda _t: None,
        orchestrator=orch,
    )
    long_ans = "项目里用 Redis 做分布式锁，过期时间 30 秒，并加了看门狗续期。"
    out = handle_inbound(
        {"sender_id": "ou_me", "content": long_ans, "message_type": "text"},
        runtime=rt,
        orchestrator=orch,
    )
    assert rt.answers == [long_ans]
    assert "锁粒度" in out[0]


def test_pause_then_chat_does_not_forward(tmp_path):
    orch = _orch(tmp_path)
    llm = QueueLlm(
        [
            {"kind": "tool", "say": "", "tool": "start_interview", "args": {}},
            {"kind": "tool", "say": "先停一下。", "tool": "pause_interview", "args": {}},
            {"kind": "chat", "say": "飞书默认 8 轮，跳过手撕。", "tool": None, "args": {}},
        ]
    )
    rt = FakeRuntime(llm)
    handle_inbound(
        {"sender_id": "ou_me", "content": "开始", "message_type": "text"},
        runtime=rt,
        emit=lambda _t: None,
        orchestrator=orch,
    )
    pause = handle_inbound(
        {"sender_id": "ou_me", "content": "先暂停", "message_type": "text"},
        runtime=rt,
        orchestrator=orch,
    )
    assert "停" in pause[0]
    assert rt.abandoned == []
    chat = handle_inbound(
        {"sender_id": "ou_me", "content": "默认几轮", "message_type": "text"},
        runtime=rt,
        orchestrator=orch,
    )
    assert rt.answers == []
    assert "8 轮" in chat[0]


def test_resume_web_session(tmp_path):
    llm = QueueLlm(
        [{"kind": "tool", "say": "", "tool": "resume_interview", "args": {"session_id": 88}}]
    )
    rt = FakeRuntime(llm)
    rt.history = [
        {
            "id": 88,
            "status": "active",
            "target_role": "Java 后端",
            "rounds_used": 2,
            "question_count": 8,
            "resumable": True,
        }
    ]
    out = handle_inbound(
        {"sender_id": "ou_me", "content": "继续网页那场", "message_type": "text"},
        runtime=rt,
        orchestrator=_orch(tmp_path),
    )
    assert rt.resumed == [88]
    assert any("Redis" in x or "接上" in x for x in out)


def test_list_then_resume_two_hops(tmp_path):
    llm = QueueLlm(
        [
            {"kind": "tool", "say": "", "tool": "list_sessions", "args": {}},
            {"kind": "tool", "say": "", "tool": "resume_interview", "args": {"session_id": 3}},
        ]
    )
    rt = FakeRuntime(llm)
    rt.history = [
        {
            "id": 3,
            "status": "abandoned",
            "target_role": "后端",
            "rounds_used": 1,
            "question_count": 8,
            "resumable": True,
        }
    ]
    out = handle_inbound(
        {"sender_id": "ou_me", "content": "我有没面完的吗，继续", "message_type": "text"},
        runtime=rt,
        orchestrator=_orch(tmp_path),
    )
    assert rt.resumed == [3]
    assert any("接上" in x or "Redis" in x for x in out)


def test_abandon_hard_stop(tmp_path):
    orch = _orch(tmp_path)
    llm = QueueLlm(
        [
            {"kind": "tool", "say": "", "tool": "start_interview", "args": {}},
            {"kind": "tool", "say": "", "tool": "abandon_interview", "args": {}},
        ]
    )
    rt = FakeRuntime(llm)
    handle_inbound(
        {"sender_id": "ou_me", "content": "开场", "message_type": "text"},
        runtime=rt,
        emit=lambda _t: None,
        orchestrator=orch,
    )
    out = handle_inbound(
        {"sender_id": "ou_me", "content": "这场不要了", "message_type": "text"},
        runtime=rt,
        orchestrator=orch,
    )
    assert rt.abandoned == [7]
    assert "退出" in out[0]


def test_norm_mode_type_specialized():
    assert _norm_mode_type("full", "八股") == ("specialized", "ba_gu")
    assert _norm_mode_type("全流程", "") == ("full", "full")
    assert _norm_mode_type("专项", "项目") == ("specialized", "project")
