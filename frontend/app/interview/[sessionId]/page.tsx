"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import CodeEditor, { type CodingProblem } from "@/components/CodeEditor";
import RecorderButton from "@/components/RecorderButton";
import SpeakerButton from "@/components/SpeakerButton";
import { Badge, ErrorBanner, IconSend, IconSparkles } from "@/components/ui";
import { ApiError, api, getToken } from "@/lib/api";
import { streamPost } from "@/lib/sse";

type Msg = { role: "interviewer" | "candidate"; text: string; streaming?: boolean };
type SessionInfo = {
  session_id: number;
  status: string;
  stage: string;
  history: Msg[];
  topics: string[];
  current_coding: CodingProblem | null;
  rounds_used: number;
  total_rounds: number;
};
type StreamDone = {
  message: string;
  stage: string;
  status: string;
  finished: boolean;
};

function StageBadge({ stage }: { stage: string }) {
  const map: Record<string, { label: string; tone: "sky" | "emerald" | "amber" | "zinc" }> = {
    INTRO: { label: "自我介绍", tone: "sky" },
    ASKING: { label: "提问中", tone: "sky" },
    ASK_BACK: { label: "反问环节", tone: "amber" },
    FINISHED: { label: "已结束", tone: "zinc" },
  };
  const s = map[stage] ?? { label: stage, tone: "zinc" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export default function ChatPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;
  const router = useRouter();
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [openingReport, setOpeningReport] = useState(false);
  const [quitting, setQuitting] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // 打字机节流：token 流式到达先入缓冲区，按 ~30ms/字 的节奏渲染，像真人打字；
  // 流式结束后不立刻刷屏，等缓冲区吐完才收尾（避免"最后一段唰地补全"）
  const typeBuf = useRef("");
  const typeTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const pendingDone = useRef<StreamDone | null>(null);
  const sawToken = useRef(false);

  async function refreshSession() {
    try {
      const d = await api<SessionInfo>(`/api/interview/session/${sessionId}`);
      setInfo(d);
      setMsgs(d.history);
    } catch {
      /* 刷新失败保持现状，下次操作会重新加载 */
    }
  }

  function finishTyping(out: StreamDone) {
    if (typeTimer.current) {
      clearInterval(typeTimer.current);
      typeTimer.current = null;
    }
    pendingDone.current = null;
    setStreaming(false);
    setSending(false);
    setMsgs((m) => {
      const last = m[m.length - 1];
      if (last && last.role === "interviewer" && last.streaming) {
        return [...m.slice(0, -1), { ...last, streaming: false }];
      }
      return m;
    });
    void refreshSession();
  }

  function startTypeTimer() {
    if (typeTimer.current) return;
    typeTimer.current = setInterval(() => {
      if (typeBuf.current) {
        const ch = typeBuf.current[0];
        typeBuf.current = typeBuf.current.slice(1);
        setMsgs((m) => {
          const last = m[m.length - 1];
          if (last && last.role === "interviewer" && last.streaming) {
            return [...m.slice(0, -1), { ...last, text: last.text + ch }];
          }
          return [...m, { role: "interviewer", text: ch, streaming: true }];
        });
        return;
      }
      if (pendingDone.current) {
        finishTyping(pendingDone.current);
      }
    }, 30);
  }

  useEffect(() => {
    return () => {
      if (typeTimer.current) clearInterval(typeTimer.current);
    };
  }, []);

  function openReport() {
    if (openingReport) return;
    setOpeningReport(true);
    // 面试结束后用硬跳转：避免 App Router 软导航卡住（页面停在面试页像“点了没反应”）
    window.location.assign(`/report/${sessionId}`);
  }

  async function quitInterview() {
    if (quitting || sending || streaming) return;
    const ok = window.confirm(
      "确定中途退出本场面试吗？退出后不会生成完整报告，可随时再开一场。"
    );
    if (!ok) return;
    setQuitting(true);
    try {
      await api(`/api/interview/session/${sessionId}/abandon`, { method: "POST" });
      window.location.assign("/dashboard");
    } catch (e) {
      setQuitting(false);
      alert(e instanceof Error ? e.message : "退出失败，请重试");
    }
  }

  function load() {
    setLoadError("");
    api<SessionInfo>(`/api/interview/session/${sessionId}`)
      .then((d) => {
        setInfo(d);
        setMsgs(d.history);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          router.replace("/login");
        } else {
          setLoadError(e instanceof Error ? e.message : "加载失败");
        }
      });
  }

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    load();
  }, [sessionId, router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, streaming, info?.current_coding]);

  // 算法题若还是旧字段（无 templates_by_mode），自动再拉一次会话以启用手撕/多语言模板
  useEffect(() => {
    if (!info?.current_coding || info.stage !== "ASKING") return;
    if (info.current_coding.templates_by_mode) return;
    api<SessionInfo>(`/api/interview/session/${sessionId}`)
      .then((d) => {
        if (d.current_coding?.templates_by_mode) setInfo(d);
      })
      .catch(() => {});
  }, [info?.current_coding, info?.stage, sessionId]);

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setSending(true);
    setMsgs((m) => [...m, { role: "candidate", text }]);
    try {
      await streamPost(
        `/api/interview/session/${sessionId}/answer/stream`,
        { text },
        {
          onToken: (t) => {
            sawToken.current = true;
            setStreaming(true);
            // 入队并启动定时渲染器（每 30ms 吐一个字）
            typeBuf.current += t;
            startTypeTimer();
          },
          onDone: (raw) => {
            const out = raw as StreamDone;
            if (sawToken.current) {
              // 有流式：等缓冲区吐完再收尾（finishTyping 由定时器触发）
              pendingDone.current = out;
              if (!typeBuf.current) finishTyping(out);
              return;
            }
            // 追问/结束等无流式 token 的消息：直接整体入流
            setSending(false);
            setMsgs((m) => [...m, { role: "interviewer", text: out.message }]);
            void refreshSession();
          },
          onError: (msg) => alert(msg),
        }
      );
    } catch (e) {
      if (typeTimer.current) clearInterval(typeTimer.current);
      typeTimer.current = null;
      pendingDone.current = null;
      setStreaming(false);
      setSending(false);
      alert(e instanceof Error ? e.message : "发送失败，请重试");
    }
  }

  // 算法题提交成功：把下一题消息入流，并刷新会话（当前题已推进）
  async function onCodingSubmitted(
    _judge: unknown,
    _review: unknown,
    message: string
  ) {
    setMsgs((m) => [...m, { role: "interviewer", text: message }]);
    try {
      const d = await api<SessionInfo>(`/api/interview/session/${sessionId}`);
      setInfo(d);
      setMsgs(d.history);
    } catch {
      /* 刷新失败保持现状 */
    }
  }

  const showCoding = info?.current_coding && info.stage === "ASKING";
  const isActive = info?.status === "active" && info?.stage !== "FINISHED";
  const isAbandoned = info?.status === "abandoned";

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col bg-zinc-50/60 dark:bg-zinc-950/40">
      {/* 顶栏 */}
      <div className="flex items-center justify-between border-b border-zinc-200/80 bg-white/80 px-5 py-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/80">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
        >
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M10 3 5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          返回
        </Link>
        <div className="flex items-center gap-2.5">
          {info ? (
            <>
              <StageBadge stage={isAbandoned ? "FINISHED" : info.stage} />
              {isAbandoned ? (
                <Badge tone="amber">已中途退出</Badge>
              ) : (
                <span className="text-xs text-zinc-400 dark:text-zinc-500">
                  {info.rounds_used}/{info.total_rounds} 轮
                  {info.topics?.length ? (
                    <span className="text-zinc-400 dark:text-zinc-500">
                      {" "}
                      （题单 {info.topics.length} 题）
                    </span>
                  ) : null}
                </span>
              )}
            </>
          ) : (
            <span className="text-xs text-zinc-400">加载中…</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {isActive && (
            <button
              type="button"
              onClick={quitInterview}
              disabled={quitting || sending || streaming}
              className="text-sm text-zinc-500 transition-colors hover:text-red-600 disabled:opacity-40 dark:text-zinc-400 dark:hover:text-red-400"
            >
              {quitting ? "退出中…" : "中途退出"}
            </button>
          )}
          <Link
            href="/interview/new"
            className="text-sm text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
          >
            新建面试
          </Link>
        </div>
      </div>

      {/* 消息区：居中收窄，气泡靠近，避免贴左右边缘显得空 */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-3.5">
          {loadError && <ErrorBanner message={loadError} onRetry={load} />}
          {msgs.map((m, i) => (
            <div
              key={i}
              className={`flex items-end gap-2 ${m.role === "candidate" ? "justify-end" : "justify-start"}`}
            >
              {m.role === "interviewer" && (
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-emerald-600 text-[10px] font-bold text-white shadow-sm shadow-sky-600/30">
                  面
                </div>
              )}
              <div
                className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed shadow-sm ${
                  m.role === "candidate"
                    ? "rounded-br-md bg-gradient-to-br from-sky-600 to-emerald-600 text-white shadow-sky-600/20 dark:from-sky-600 dark:to-emerald-600"
                    : "rounded-bl-md border border-zinc-200/80 bg-white text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100"
                }`}
              >
                <span className={`whitespace-pre-wrap ${m.streaming ? "streaming-cursor" : ""}`}>
                  {m.text}
                </span>
                {m.role === "interviewer" && !m.streaming && <SpeakerButton text={m.text} />}
              </div>
              {m.role === "candidate" && (
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zinc-200 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                  <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <circle cx="12" cy="8" r="3.5" />
                    <path d="M5 20a7 7 0 0 1 14 0" strokeLinecap="round" />
                  </svg>
                </div>
              )}
            </div>
          ))}
          {sending && !streaming && (
            <div className="flex items-end gap-2">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-emerald-600 text-[10px] font-bold text-white shadow-sm shadow-sky-600/30">
                面
              </div>
              <div className="flex items-center gap-2 rounded-2xl rounded-bl-md border border-zinc-200/80 bg-white px-3.5 py-2.5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
                <span className="flex items-center gap-1.5 text-zinc-400 dark:text-zinc-500">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </span>
                <span className="text-xs text-zinc-400 dark:text-zinc-500">
                  正在评估你的回答，准备下一问…
                </span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* 底部：输入 / 编辑器 / 结束态 */}
      <div className="border-t border-zinc-200/80 bg-white/80 p-4 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/80">
        {info?.status === "finished" || info?.stage === "FINISHED" || isAbandoned ? (
          <div className="flex flex-wrap items-center justify-center gap-3">
            <span className="inline-flex items-center gap-1.5 text-sm text-zinc-500 dark:text-zinc-400">
              <IconSparkles className="h-4 w-4 text-sky-500" />
              {isAbandoned ? "本场已中途退出" : "面试已结束"}
            </span>
            {!isAbandoned && (
              <button
                type="button"
                onClick={openReport}
                disabled={openingReport}
                className="rounded-xl bg-gradient-to-r from-sky-600 to-emerald-600 px-6 py-2 text-sm font-medium text-white shadow-md shadow-sky-600/25 transition-all hover:from-sky-500 hover:to-emerald-500 disabled:opacity-70"
              >
                {openingReport ? "正在打开报告…" : "查看面试报告"}
              </button>
            )}
            {isAbandoned && (
              <Link
                href="/interview/new"
                className="rounded-xl bg-gradient-to-r from-sky-600 to-emerald-600 px-6 py-2 text-sm font-medium text-white shadow-md shadow-sky-600/25 transition-all hover:from-sky-500 hover:to-emerald-500"
              >
                再开一场
              </Link>
            )}
          </div>
        ) : showCoding && info.current_coding ? (
          <div className="mx-auto h-[58vh] w-full max-w-5xl">
            <CodeEditor
              key={`${info.current_coding.slug}-${info.current_coding.templates_by_mode ? "v2" : "v1"}`}
              sessionId={sessionId}
              problem={info.current_coding}
              onSubmitted={onCodingSubmitted}
            />
          </div>
        ) : (
          <div className="mx-auto flex max-w-2xl items-end gap-2.5">
            <RecorderButton onTranscribed={(t) => setInput(t)} />
            <div className="flex flex-1 items-end rounded-2xl border border-zinc-200 bg-white shadow-sm transition-all focus-within:border-sky-400 focus-within:ring-2 focus-within:ring-sky-500/20 dark:border-zinc-700 dark:bg-zinc-900 dark:focus-within:border-sky-500">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                rows={1}
                placeholder="输入你的回答…（Enter 发送，Shift+Enter 换行）"
                className="max-h-32 min-h-[44px] flex-1 resize-none bg-transparent px-4 py-3 text-sm text-zinc-900 outline-none placeholder-zinc-400 dark:text-zinc-50 dark:placeholder-zinc-500"
              />
              <button
                onClick={send}
                disabled={sending || !input.trim()}
                title="发送"
                className="m-1.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-sky-600 text-white shadow-sm shadow-sky-600/25 transition-all hover:bg-sky-500 disabled:opacity-40"
              >
                <IconSend className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
