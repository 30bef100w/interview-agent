"""飞书私聊通道：管家判别后转给现有面试栈。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

HELP_TEXT = """我是深问的飞书管家，不是面试官。题目仍由深问面试引擎出。

直接用自然语言就行，例如：
• 深问怎么用 / 开场要哪些参数
• 按默认开始（最新简历、全流程 8 轮，飞书跳过手撕）
• 用最新简历面 Java 后端
• 我还有没面完的吗 / 继续上一场
• 先暂停一下（通道关掉，网页那场还在）
• 这场不要了（彻底结束，没有完整报告）

完整报告和手撕请用网页。还没绑定的话，打开网页用飞书登录，或到设置里点「绑定飞书」。"""


@dataclass
class Intent:
    kind: str  # help | start | stop | status | answer
    role: str = ""
    company: str = ""
    rounds: int | None = None
    interview_mode: str = "full"
    interview_type: str = "full"
    text: str = ""


@dataclass
class ChannelUser:
    id: int
    username: str


@dataclass
class ChannelSession:
    id: int
    status: str
    stage: str = ""
    coding: bool = False
    error: str = ""


class ChannelRuntime(Protocol):
    def resolve_sender(self, open_id: str) -> ChannelUser | None: ...

    def latest_open_session(self, user_id: int) -> ChannelSession | None: ...

    def has_resume(self, user_id: int) -> bool: ...

    def start_session(
        self,
        user: ChannelUser,
        *,
        role: str,
        company: str,
        rounds: int,
        interview_mode: str,
        interview_type: str,
        on_progress: Callable[[str], None],
        resume_id: int | None = None,
    ) -> ChannelSession: ...

    def submit_answer(self, user: ChannelUser, session_id: int, text: str) -> dict: ...

    def abandon(self, user: ChannelUser, session_id: int) -> None: ...

    def session_url(self, session_id: int) -> str: ...

    def llm_for(self, user: ChannelUser) -> Any: ...

    def list_resumes(self, user: ChannelUser) -> list[dict]: ...

    def list_sessions(self, user: ChannelUser, limit: int = 12) -> list[dict]: ...

    def get_session(self, user: ChannelUser, session_id: int) -> dict: ...

    def get_account(self, user: ChannelUser) -> dict: ...

    def resume_session(self, user: ChannelUser, session_id: int) -> dict: ...


_START_RE = re.compile(r"^(开始面试|开练|开始)(?:\s+(.+))?$", re.S)
_ROUNDS_RE = re.compile(r"^(\d{1,2})轮?$")
_SPECIAL_TYPE = {
    "八股": "ba_gu",
    "项目": "project",
    "hr": "hr",
    "HR": "hr",
    "人力": "hr",
}


def parse_bind_map(raw: str) -> dict[str, str]:
    """`ou_xxx:username,ou_yyy:other` → {open_id: username}。"""
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if ":" not in part:
            continue
        open_id, username = part.split(":", 1)
        open_id, username = open_id.strip(), username.strip()
        if open_id and username:
            out[open_id] = username
    return out


def parse_intent(text: str) -> Intent:
    raw = (text or "").strip()
    if not raw:
        return Intent(kind="help")
    compact = raw.strip("。.!！").strip()
    low = compact.lower()
    if low in {"帮助", "help", "菜单", "?", "？"}:
        return Intent(kind="help")
    if compact in {"结束", "退出", "不面了"}:
        return Intent(kind="stop")
    if compact in {"状态", "进度"}:
        return Intent(kind="status")
    m = _START_RE.match(compact)
    if m:
        return _parse_start_tail(m.group(2) or "")
    return Intent(kind="answer", text=raw)


def _parse_start_tail(tail: str) -> Intent:
    intent = Intent(kind="start")
    tokens = [t for t in (tail or "").split() if t]
    if tokens and _ROUNDS_RE.match(tokens[-1]):
        n = int(_ROUNDS_RE.match(tokens[-1]).group(1))
        if 4 <= n <= 20:
            intent.rounds = n
            tokens = tokens[:-1]
    if tokens and tokens[0] in {"专项", "八股", "项目", "hr", "HR", "人力"}:
        intent.interview_mode = "specialized"
        head = tokens.pop(0)
        if head == "专项" and tokens and tokens[0] in _SPECIAL_TYPE:
            intent.interview_type = _SPECIAL_TYPE[tokens.pop(0)]
        elif head in _SPECIAL_TYPE:
            intent.interview_type = _SPECIAL_TYPE[head]
        else:
            intent.interview_type = "ba_gu"
    if tokens:
        intent.role = tokens[0][:128]
    if len(tokens) >= 2:
        intent.company = " ".join(tokens[1:])[:128]
    return intent


def format_report(report: dict | None, url: str) -> str:
    report = report or {}
    lines = ["本场面试结束。"]
    score = report.get("overall_score")
    if score is None:
        score = report.get("score")
    if score is None:
        dims = report.get("dimension_scores") or {}
        nums = []
        for v in dims.values():
            try:
                nums.append(float(v))
            except (TypeError, ValueError):
                continue
        if nums:
            score = round(sum(nums) / len(nums), 1)
    if score is not None:
        lines.append(f"综合分：{score}")
    summary = str(report.get("summary") or "").strip()
    if summary:
        lines.append(summary[:800])
    if url:
        lines.append(f"完整报告：{url}")
    return "\n\n".join(lines)


def handle_inbound(
    event: dict,
    *,
    runtime: ChannelRuntime,
    emit: Callable[[str], None] | None = None,
    orchestrator=None,
) -> list[str]:
    """处理一条飞书私聊：先管家判别，再转现有面试栈。"""
    emit = emit or (lambda _t: None)
    sender = str(event.get("sender_id") or "").strip()
    user = runtime.resolve_sender(sender)
    if user is None:
        return [
            "这个飞书号还没绑定深问。请打开网页用「飞书登录」，或登录后到设置里点「绑定飞书」。绑定后回到这里直接说想面什么岗即可。"
        ]

    msg_type = str(event.get("message_type") or "text")
    if msg_type not in {"text", "post"}:
        return ["飞书面试通道目前只收文字。简历请先在网页上传，手撕也请用网页编辑器。"]

    text = str(event.get("content") or "")
    if orchestrator is None:
        from app.services.feishu_orchestrator import default_orchestrator

        orchestrator = default_orchestrator()
    return orchestrator.handle(sender, text, user, runtime, emit)
