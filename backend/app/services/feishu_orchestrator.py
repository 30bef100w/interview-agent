"""飞书智能通信管家：判别闲聊 / 指令 / 作答，工具转给现有面试栈。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.services.feishu_channel import (
    ChannelSession,
    ChannelUser,
    HELP_TEXT,
    format_report,
    parse_intent,
)
from app.services.job_roles import all_categories, all_roles, resolve_target_roles

logger = logging.getLogger("app.feishu_orchestrator")

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "feishu_orchestrator"
_SAFE_ID = re.compile(r"[^a-zA-Z0-9_-]+")
_MAX_TURNS = 12
_MAX_HOPS = 2

QUERY_TOOLS = {
    "list_resumes",
    "list_roles",
    "list_sessions",
    "get_session",
    "get_account",
}
ACTION_TOOLS = {
    "start_interview",
    "pause_interview",
    "resume_interview",
    "abandon_interview",
}

SYSTEM_PROMPT = """你是「深问」的飞书通信管家，不是面试官。你不出题、不评分、不编简历。

深问是模拟技术面试产品。网页可开练、上传简历、看报告、写手撕代码。飞书里你负责：解释用法、收齐开场参数、按需查看网页同一份状态，再用工具开场/暂停/续面/结束。真正的题目由面试引擎生成。

开一场需要：
- 简历（必选；用户说默认/随便/最新 → 用最新一份。没有简历就请去网页上传）
- 模式：full 全流程混合（默认）或 specialized 专项
- 专项类型：ba_gu 八股 / project 项目 / hr 行为面（全流程时 interview_type 用 full）
- 轮次 4–20，默认 8
- 可选岗位、企业
飞书默认 skip_coding=true（手撕请用网页）。

工具（kind=tool 时填写 tool + args）：
- list_resumes / list_roles / list_sessions / get_session / get_account
- start_interview：args 可含 resume_id, interview_mode, interview_type, question_count, target_role, target_company
- pause_interview：只关掉飞书通道，网页那场仍进行中，之后消息不当作答
- resume_interview：args.session_id 可省略（用当前挂着的场）。把通道挂回网页已有场并重发上一问
- abandon_interview：彻底结束，不生成完整报告

kind 只能是：
- chat：闲聊或用法说明，自己用 say 回答，不调面试引擎
- tool：要查状态或改变场次
- forward_answer：当前 phase=interviewing，且用户这句话是面试作答（不是暂停/结束/换场）。原文会交给引擎，不要改写答案，say 可空

规则：
- 每一句都先判别。短句、祈使、问用法 → chat 或 tool。长技术回答且正在面 → forward_answer。
- 缺参数且用户没说默认时，先问 1～2 项，或 list_resumes / list_sessions 再问选哪份/哪场。
- 已有未完成场时，开新场前应问：继续上一场还是新开。
- 用户说「先停一下/暂停/我问你点事」→ pause_interview，不要 abandon。
- 「这场不要了/彻底结束」才 abandon_interview。
- 已出报告的场不能续。

只输出一个 JSON 对象：
{"kind":"chat|tool|forward_answer","say":"...","tool":null或工具名,"args":{}}
"""


@dataclass
class WorkingMemory:
    phase: str = "idle"  # idle | interviewing
    session_id: int | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    turns: list[dict[str, str]] = field(default_factory=list)
    last_tool: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> WorkingMemory:
        data = data or {}
        sid = data.get("session_id")
        try:
            sid_i = int(sid) if sid is not None else None
        except (TypeError, ValueError):
            sid_i = None
        phase = str(data.get("phase") or "idle")
        if phase not in {"idle", "interviewing"}:
            phase = "idle"
        return cls(
            phase=phase,
            session_id=sid_i,
            slots=dict(data.get("slots") or {}),
            turns=list(data.get("turns") or [])[-_MAX_TURNS:],
            last_tool=data.get("last_tool") if isinstance(data.get("last_tool"), dict) else None,
        )


class MemoryStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else _DATA_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, open_id: str) -> Path:
        key = _SAFE_ID.sub("_", (open_id or "unknown").strip())[:80] or "unknown"
        return self.root / f"{key}.json"

    def load(self, open_id: str) -> WorkingMemory:
        path = self._path(open_id)
        if not path.is_file():
            return WorkingMemory()
        try:
            return WorkingMemory.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return WorkingMemory()

    def save(self, open_id: str, memory: WorkingMemory) -> None:
        memory.turns = memory.turns[-_MAX_TURNS:]
        path = self._path(open_id)
        path.write_text(
            json.dumps(memory.to_dict(), ensure_ascii=False, indent=0),
            encoding="utf-8",
        )


def roles_catalog_brief() -> list[dict[str, Any]]:
    roles = all_roles()
    out: list[dict[str, Any]] = []
    for cat, ids in all_categories().items():
        names = [str(roles.get(rid, {}).get("name") or rid) for rid in ids]
        out.append({"category": cat, "roles": names})
    return out


def _clip(text: str, n: int = 400) -> str:
    raw = (text or "").strip()
    if len(raw) <= n:
        return raw
    return raw[: n - 1] + "…"


class FeishuOrchestrator:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    def handle(
        self,
        open_id: str,
        text: str,
        user: ChannelUser,
        runtime: Any,
        emit: Callable[[str], None],
    ) -> list[str]:
        memory = self.store.load(open_id)
        decision = self._decide(text, memory, user, runtime)
        replies = self._dispatch(decision, text, memory, user, runtime, emit)
        self._remember(memory, text, replies)
        self.store.save(open_id, memory)
        return [r for r in replies if r]

    def _decide(self, text: str, memory: WorkingMemory, user: ChannelUser, runtime: Any) -> dict:
        llm = None
        getter = getattr(runtime, "llm_for", None)
        if callable(getter):
            try:
                llm = getter(user)
            except Exception:
                logger.exception("llm_for failed, fallback")
        if llm is None:
            return self._fallback_decision(text, memory)
        payload = self._user_payload(text, memory)
        try:
            raw = llm.chat_json(SYSTEM_PROMPT, payload)
            decision = _parse_decision(raw)
            if decision["kind"] == "tool" and not decision["tool"]:
                decision["kind"] = "chat"
            return decision
        except Exception:
            logger.exception("orchestrator json failed, fallback")
            return self._fallback_decision(text, memory)

    def _dispatch(
        self,
        decision: dict,
        text: str,
        memory: WorkingMemory,
        user: ChannelUser,
        runtime: Any,
        emit: Callable[[str], None],
    ) -> list[str]:
        hops = 0
        while hops < _MAX_HOPS:
            hops += 1
            kind = decision["kind"]
            if kind == "forward_answer":
                return self._forward_answer(text, memory, user, runtime)
            if kind != "tool":
                say = decision.get("say") or "我在。可以直接说想面什么岗，或问深问怎么用。"
                return [say]
            tool = decision.get("tool") or ""
            args = decision.get("args") if isinstance(decision.get("args"), dict) else {}
            if tool in ACTION_TOOLS:
                return self._run_action(tool, args, decision.get("say") or "", memory, user, runtime, emit)
            if tool not in QUERY_TOOLS:
                return [decision.get("say") or f"我还不会这个操作（{tool}）。"]
            result = self._run_query(tool, args, memory, user, runtime)
            memory.last_tool = {"tool": tool, "result": result}
            llm = getattr(runtime, "llm_for", lambda _u: None)(user)
            if llm is None or hops >= _MAX_HOPS:
                return [decision.get("say") or _format_query_fallback(tool, result)]
            follow = self._user_payload(text, memory) + "\n请根据工具结果用 JSON 回复用户（优先 kind=chat，必要时再 tool）。"
            try:
                decision = _parse_decision(llm.chat_json(SYSTEM_PROMPT, follow))
            except Exception:
                return [decision.get("say") or _format_query_fallback(tool, result)]
        return [decision.get("say") or "我没理解清楚，请再说一次。"]

    def _run_query(self, tool: str, args: dict, memory: WorkingMemory, user: ChannelUser, runtime: Any) -> Any:
        if tool == "list_resumes":
            return runtime.list_resumes(user)
        if tool == "list_roles":
            return roles_catalog_brief()
        if tool == "list_sessions":
            return runtime.list_sessions(user)
        if tool == "get_account":
            return runtime.get_account(user)
        sid = _int_or_none(args.get("session_id")) or memory.session_id
        if sid is None:
            latest = runtime.latest_open_session(user.id)
            sid = latest.id if latest else None
        if sid is None:
            return {"error": "当前没有挂着的场次"}
        return runtime.get_session(user, sid)

    def _run_action(
        self,
        tool: str,
        args: dict,
        say: str,
        memory: WorkingMemory,
        user: ChannelUser,
        runtime: Any,
        emit: Callable[[str], None],
    ) -> list[str]:
        if tool == "pause_interview":
            memory.phase = "idle"
            extra = say or "好，先暂停面试通道。这场还在，说「继续」就能接上。现在可以问用法或闲聊。"
            return [extra]
        if tool == "abandon_interview":
            sid = _int_or_none(args.get("session_id")) or memory.session_id
            if sid is None:
                latest = runtime.latest_open_session(user.id)
                sid = latest.id if latest else None
            if sid is None:
                return ["当前没有进行中的面试。"]
            runtime.abandon(user, sid)
            memory.phase = "idle"
            memory.session_id = None
            return [say or "已退出本场。随时可以再开一场，或从历史未完成场继续。"]
        if tool == "resume_interview":
            sid = _int_or_none(args.get("session_id")) or memory.session_id
            if sid is None:
                rows = runtime.list_sessions(user)
                resumable = [r for r in rows if r.get("resumable")]
                if not resumable:
                    return ["没有可继续的未完成面试。可以说想面的岗位，我帮你新开一场。"]
                if len(resumable) > 1 and not args.get("session_id"):
                    memory.last_tool = {"tool": "list_sessions", "result": resumable}
                    lines = ["有几场还没面完，回我编号即可："]
                    for r in resumable[:8]:
                        lines.append(_session_line(r))
                    return ["\n".join(lines)]
                sid = int(resumable[0]["id"])
            out = runtime.resume_session(user, sid)
            if not out.get("ok"):
                return [str(out.get("error") or "没法续这场。")]
            memory.phase = "interviewing"
            memory.session_id = int(out["session_id"])
            return _resume_replies(out, say)
        if tool == "start_interview":
            return self._start(args, say, memory, user, runtime, emit)
        return [f"未知动作 {tool}"]

    def _start(
        self,
        args: dict,
        say: str,
        memory: WorkingMemory,
        user: ChannelUser,
        runtime: Any,
        emit: Callable[[str], None],
    ) -> list[str]:
        if not runtime.has_resume(user.id):
            return ["还没有简历。请先在网页上传一份，再回飞书告诉我开场。"]
        role = str(args.get("target_role") or args.get("role") or memory.slots.get("target_role") or "").strip()
        if role:
            mapped = resolve_target_roles(role)
            if mapped:
                memory.slots["target_role_id"] = mapped[0]
        company = str(args.get("target_company") or args.get("company") or memory.slots.get("target_company") or "").strip()
        mode, itype = _norm_mode_type(
            args.get("interview_mode") or memory.slots.get("interview_mode"),
            args.get("interview_type") or memory.slots.get("interview_type"),
        )
        rounds = _int_or_none(args.get("question_count") or args.get("rounds") or memory.slots.get("question_count")) or 8
        resume_id = _int_or_none(args.get("resume_id") or memory.slots.get("resume_id"))
        memory.slots.update(
            {
                "target_role": role,
                "target_company": company,
                "interview_mode": mode,
                "interview_type": itype,
                "question_count": rounds,
            }
        )
        if resume_id:
            memory.slots["resume_id"] = resume_id
        emit("收到，正在按网页同一套配置规划本场，通常要一两分钟…")
        sess: ChannelSession = runtime.start_session(
            user,
            role=role,
            company=company,
            rounds=rounds,
            interview_mode=mode,
            interview_type=itype,
            on_progress=emit,
            resume_id=resume_id,
        )
        if sess.status != "active":
            return [sess.error or "规划失败，请稍后重试，或到网页上看失败原因。"]
        memory.phase = "interviewing"
        memory.session_id = sess.id
        hint = f"本场 #{sess.id} 已就绪。先用一两句话自我介绍，然后面试官开始提问。"
        url = runtime.session_url(sess.id)
        if url:
            hint += f"\n网页同步：{url}"
        if say and say not in hint:
            return [say, hint]
        return [hint]

    def _forward_answer(
        self, text: str, memory: WorkingMemory, user: ChannelUser, runtime: Any
    ) -> list[str]:
        sid = memory.session_id
        if sid is None:
            latest = runtime.latest_open_session(user.id)
            if latest and latest.status == "active":
                sid = latest.id
                memory.session_id = sid
                memory.phase = "interviewing"
        if sid is None:
            return ["还没开场。告诉我岗位和简历（或说按默认），我帮你开一场。"]
        sess = runtime.latest_open_session(user.id)
        if sess and sess.id == sid and sess.status == "creating":
            return ["题单还在规划，稍等半分钟再答。"]
        out = runtime.submit_answer(user, sid, text)
        message = str(out.get("message") or "").strip() or "（面试官没有返回文本）"
        if out.get("finished"):
            memory.phase = "idle"
            memory.session_id = None
            return [format_report(out.get("report"), runtime.session_url(sid))]
        if out.get("coding"):
            url = runtime.session_url(sid)
            message += "\n\n这题是手撕，飞书里不方便写代码。"
            if url:
                message += f"请打开 {url} 作答，或回复「跳过」。"
            else:
                message += "请到网页面试间作答，或回复「跳过」。"
        memory.phase = "interviewing"
        memory.session_id = sid
        return [message]

    def _remember(self, memory: WorkingMemory, user_text: str, replies: list[str]) -> None:
        memory.turns.append({"role": "user", "text": _clip(user_text, 300)})
        joined = _clip("\n".join(replies), 400)
        if memory.phase == "interviewing" and "本场" not in joined:
            joined = "(已转交面试引擎)"
        memory.turns.append({"role": "assistant", "text": joined})
        memory.turns = memory.turns[-_MAX_TURNS:]

    def _user_payload(self, text: str, memory: WorkingMemory) -> str:
        brief = {
            "phase": memory.phase,
            "session_id": memory.session_id,
            "slots": memory.slots,
            "last_tool": _compress_tool(memory.last_tool),
            "recent": memory.turns[-8:],
        }
        return (
            "工作记忆（仅飞书通道开关，面试进度以网页数据库为准）：\n"
            + json.dumps(brief, ensure_ascii=False)
            + "\n用户说："
            + (text or "")
        )

    def _fallback_decision(self, text: str, memory: WorkingMemory) -> dict:
        intent = parse_intent(text)
        if intent.kind == "help":
            return {"kind": "chat", "say": HELP_TEXT, "tool": None, "args": {}}
        if intent.kind == "stop":
            return {"kind": "tool", "say": "", "tool": "abandon_interview", "args": {}}
        if intent.kind == "status":
            return {"kind": "tool", "say": "", "tool": "get_session", "args": {}}
        if intent.kind == "start":
            return {
                "kind": "tool",
                "say": "",
                "tool": "start_interview",
                "args": {
                    "target_role": intent.role,
                    "target_company": intent.company,
                    "question_count": intent.rounds or 8,
                    "interview_mode": intent.interview_mode,
                    "interview_type": intent.interview_type,
                },
            }
        if memory.phase == "interviewing":
            return {"kind": "forward_answer", "say": "", "tool": None, "args": {}}
        return {
            "kind": "chat",
            "say": "我是深问管家。想开场的话直接说岗位，或说「按默认开始」；也可以问用法、查未完成的面试。",
            "tool": None,
            "args": {},
        }


def _parse_decision(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    kind = str(raw.get("kind") or "chat").strip().lower()
    if kind not in {"chat", "tool", "forward_answer"}:
        kind = "chat"
    tool = str(raw.get("tool") or "").strip() or None
    args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
    return {"kind": kind, "say": str(raw.get("say") or "").strip(), "tool": tool, "args": args}


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _norm_mode_type(mode: Any, itype: Any) -> tuple[str, str]:
    mode_s = str(mode or "").strip().lower()
    type_s = str(itype or "").strip().lower()
    aliases_type = {
        "八股": "ba_gu",
        "bagu": "ba_gu",
        "ba_gu": "ba_gu",
        "项目": "project",
        "project": "project",
        "hr": "hr",
        "人力": "hr",
        "full": "full",
        "全流程": "full",
    }
    aliases_mode = {
        "专项": "specialized",
        "specialized": "specialized",
        "全流程": "full",
        "full": "full",
        "混合": "full",
    }
    type_s = aliases_type.get(type_s, type_s or "full")
    mode_s = aliases_mode.get(mode_s, mode_s or "full")
    if type_s in {"ba_gu", "project", "hr"} and mode_s == "full":
        mode_s = "specialized"
    if mode_s not in {"full", "specialized"}:
        mode_s = "full"
    if type_s not in {"full", "ba_gu", "project", "hr"}:
        type_s = "full" if mode_s == "full" else "ba_gu"
    if mode_s == "full":
        type_s = "full"
    return mode_s, type_s


def _compress_tool(last: dict | None) -> dict | None:
    if not last:
        return None
    result = last.get("result")
    if isinstance(result, list):
        result = result[:8]
    return {"tool": last.get("tool"), "result": result}


def _format_query_fallback(tool: str, result: Any) -> str:
    if tool == "list_resumes" and isinstance(result, list):
        if not result:
            return "还没有简历，请先到网页上传。"
        lines = ["你的简历："]
        for i, row in enumerate(result[:8], 1):
            latest = "（最新）" if i == 1 else ""
            lines.append(f"#{row.get('id')} {row.get('filename')}{latest}")
        lines.append("回我用哪一份，或说用最新。")
        return "\n".join(lines)
    if tool == "list_sessions" and isinstance(result, list):
        if not result:
            return "还没有面试记录。"
        lines = ["最近面试："]
        lines.extend(_session_line(r) for r in result[:8])
        return "\n".join(lines)
    if tool == "list_roles" and isinstance(result, list):
        bits = [f"{c.get('category')}：{'、'.join(c.get('roles') or [])}" for c in result[:8]]
        return "岗位目录：\n" + "\n".join(bits)
    if isinstance(result, dict) and result.get("error"):
        return str(result["error"])
    if isinstance(result, dict):
        bits = [f"{k}={v}" for k, v in result.items() if v not in (None, "", [])]
        return "当前状态：" + "，".join(bits[:8])
    return json.dumps(result, ensure_ascii=False)[:800]


def _session_line(row: dict) -> str:
    flag = "可续" if row.get("resumable") else row.get("status")
    role = row.get("target_role") or "未指定岗位"
    return (
        f"#{row.get('id')} {role} · {flag} · "
        f"{row.get('rounds_used')}/{row.get('question_count')} 轮"
    )


def _resume_replies(out: dict, say: str) -> list[str]:
    sid = out.get("session_id")
    msg = str(out.get("message") or "").strip()
    head = say or f"接上本场 #{sid}。上一问如下："
    url = str(out.get("url") or "")
    if url:
        head += f"\n网页同步：{url}"
    if out.get("coding") and url:
        msg += f"\n\n这题是手撕，请打开 {url} 作答，或回复「跳过」。"
    if msg:
        return [head, msg]
    return [head]


_default = FeishuOrchestrator()


def default_orchestrator() -> FeishuOrchestrator:
    return _default
