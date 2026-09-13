"""飞书通道：绑定校验 + 管家接入（关键词 parse_intent 仅作兜底对照）。"""
import json

from app.services.feishu_channel import (
    ChannelSession,
    ChannelUser,
    format_report,
    handle_inbound,
    parse_bind_map,
    parse_intent,
)
from app.services.feishu_cli import build_text_content, split_message
from app.services.feishu_orchestrator import FeishuOrchestrator, MemoryStore, WorkingMemory


class ParseIntentLlm:
    """单测用：按旧关键词规则生成管家 JSON，便于对照通道行为。"""

    def chat_json(self, system: str, user: str, **_kwargs) -> dict:
        text = user
        if "用户说：" in user:
            text = user.split("用户说：", 1)[1].strip()
        phase = "idle"
        if '"phase": "interviewing"' in user or '"phase":"interviewing"' in user:
            phase = "interviewing"
        mem = WorkingMemory(phase=phase)
        return FeishuOrchestrator()._fallback_decision(text, mem)


class FakeRuntime:
    def __init__(self):
        self.user = ChannelUser(id=1, username="xuyongqi")
        self.resume = True
        self.session: ChannelSession | None = None
        self.answers: list[str] = []
        self.progress: list[str] = []
        self.abandoned = False
        self.start_status = "active"
        self.llm = ParseIntentLlm()
        self.resumed_id = None

    def resolve_sender(self, open_id: str) -> ChannelUser | None:
        return self.user if open_id == "ou_me" else None

    def latest_open_session(self, user_id: int) -> ChannelSession | None:
        return self.session

    def has_resume(self, user_id: int) -> bool:
        return self.resume

    def start_session(self, user, **kwargs) -> ChannelSession:
        on_progress = kwargs.get("on_progress")
        if on_progress:
            on_progress("规划中 40% · 出题")
            self.progress.append("规划中 40% · 出题")
        self.session = ChannelSession(id=42, status=self.start_status, stage="INTRO")
        return self.session

    def submit_answer(self, user, session_id: int, text: str) -> dict:
        self.answers.append(text)
        if text == "结束本场":
            return {
                "message": "面试结束，报告已生成。",
                "finished": True,
                "report": {"summary": "表达清楚", "overall_score": 7.5},
            }
        return {"message": "请介绍一下项目里的锁。", "finished": False, "coding": text == "代码"}

    def abandon(self, user, session_id: int) -> None:
        self.abandoned = True
        self.session = None

    def session_url(self, session_id: int) -> str:
        return f"https://deeplyask.online/interview/{session_id}"

    def llm_for(self, user: ChannelUser):
        return self.llm

    def list_resumes(self, user: ChannelUser) -> list[dict]:
        if not self.resume:
            return []
        return [{"id": 1, "filename": "cv.pdf", "created_at": ""}]

    def list_sessions(self, user: ChannelUser, limit: int = 12) -> list[dict]:
        if not self.session:
            return []
        return [
            {
                "id": self.session.id,
                "status": self.session.status,
                "target_role": "后端",
                "rounds_used": 0,
                "question_count": 8,
                "resumable": self.session.status in {"active", "creating", "abandoned"},
            }
        ]

    def get_session(self, user: ChannelUser, session_id: int) -> dict:
        if not self.session or self.session.id != session_id:
            return {"error": "会话不存在"}
        return {"id": session_id, "status": self.session.status, "stage": self.session.stage}

    def get_account(self, user: ChannelUser) -> dict:
        return {"has_resume": self.resume, "resume_count": 1 if self.resume else 0, "platform_quota": 3}

    def resume_session(self, user: ChannelUser, session_id: int) -> dict:
        self.resumed_id = session_id
        self.session = ChannelSession(id=session_id, status="active", stage="ASKING")
        return {
            "ok": True,
            "session_id": session_id,
            "message": "请介绍一下项目里的锁。",
            "url": self.session_url(session_id),
        }


def test_parse_bind_map():
    assert parse_bind_map(" ou_1:alice , ou_2:bob ") == {"ou_1": "alice", "ou_2": "bob"}


def test_parse_intent_start_variants():
    a = parse_intent("开始 后端 字节跳动 8")
    assert a.kind == "start"
    assert a.role == "后端"
    assert a.company == "字节跳动"
    assert a.rounds == 8
    b = parse_intent("开始 八股")
    assert b.interview_mode == "specialized"
    assert b.interview_type == "ba_gu"
    d = parse_intent("开始 专项 项目 6")
    assert d.interview_type == "project"
    assert d.rounds == 6
    assert parse_intent("帮助").kind == "help"
    assert parse_intent("结束").kind == "stop"
    assert parse_intent("我做过交易系统。").kind == "answer"


def test_unbound_user(tmp_path):
    rt = FakeRuntime()
    orch = FeishuOrchestrator(MemoryStore(tmp_path))
    out = handle_inbound(
        {"sender_id": "ou_other", "content": "开始", "message_type": "text"},
        runtime=rt,
        orchestrator=orch,
    )
    assert "绑定" in out[0]


def test_start_and_answer(tmp_path):
    rt = FakeRuntime()
    orch = FeishuOrchestrator(MemoryStore(tmp_path))
    emitted = []
    start = handle_inbound(
        {"sender_id": "ou_me", "content": "开始 后端", "message_type": "text"},
        runtime=rt,
        emit=emitted.append,
        orchestrator=orch,
    )
    assert any("规划" in x for x in emitted)
    assert "自我介绍" in start[0]
    assert rt.session is not None
    ans = handle_inbound(
        {"sender_id": "ou_me", "content": "我叫许永琪，做过面试引擎。", "message_type": "text"},
        runtime=rt,
        orchestrator=orch,
    )
    assert "锁" in ans[0]
    done = handle_inbound(
        {"sender_id": "ou_me", "content": "结束本场", "message_type": "text"},
        runtime=rt,
        orchestrator=orch,
    )
    assert "综合分：7.5" in done[0]
    assert "deeplyask.online/interview/42" in done[0]


def test_stop_and_no_resume(tmp_path):
    rt = FakeRuntime()
    orch = FeishuOrchestrator(MemoryStore(tmp_path))
    rt.session = ChannelSession(id=3, status="active", stage="ASKING")
    out = handle_inbound(
        {"sender_id": "ou_me", "content": "结束", "message_type": "text"},
        runtime=rt,
        orchestrator=orch,
    )
    assert rt.abandoned is True
    assert "退出" in out[0]
    rt.resume = False
    out = handle_inbound(
        {"sender_id": "ou_me", "content": "开始", "message_type": "text"},
        runtime=rt,
        orchestrator=orch,
    )
    assert "简历" in out[0]


def test_format_report_and_split():
    text = format_report({"summary": "还行", "overall_score": 6}, "https://x/1")
    assert "综合分：6" in text
    parts = split_message("abcd", 2)
    assert parts == ["ab", "cd"]


def test_build_text_content_keeps_list_after_colon():
    raw = "就是这三件事：\n\n1. 简历\n2. 模式\n3. 轮次"
    payload = build_text_content(raw)
    assert "\n" not in payload
    body = json.loads(payload)
    assert "1. 简历" in body["text"]
    assert body["text"].startswith("就是这三件事：")
