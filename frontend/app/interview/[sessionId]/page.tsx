"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { type PointerEvent, type ReactNode, useCallback, useEffect, useRef, useState } from "react";

import CodeEditor, { type CodingProblem } from "@/components/CodeEditor";
import AnswerComposer, { type AnswerComposerHandle } from "@/components/interview/AnswerComposer";
import DisconnectOverlay from "@/components/interview/DisconnectOverlay";
import InterviewStatusBar from "@/components/interview/InterviewStatusBar";
import MessageTimeline, { type ChatMsg } from "@/components/interview/MessageTimeline";
import { Badge, ErrorBanner, IconSparkles } from "@/components/ui";
import { ApiError, api, getToken } from "@/lib/api";
import { streamPost } from "@/lib/sse";
import { useInterviewWebSocket } from "@/hooks/useInterviewWebSocket";

type SessionInfo = {
  session_id: number;
  status: string;
  stage: string;
  history: ChatMsg[];
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

const TTS_KEY = "fa_tts_autoplay";

function ResizableCodingFrame({ children }: { children: ReactNode }) {
  const [height, setHeight] = useState<number | null>(null);
  const drag = useRef<{ y: number; h: number } | null>(null);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.parentElement;
    if (!box) return;
    drag.current = { y: e.clientY, h: box.getBoundingClientRect().height };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const next = drag.current.h + (drag.current.y - e.clientY);
    const max = typeof window === "undefined" ? next : window.innerHeight * 0.9;
    setHeight(Math.round(Math.min(Math.max(next, 240), max)));
  };
  const onPointerUp = () => {
    drag.current = null;
  };

  return (
    <div
      className="relative mx-auto w-full max-w-5xl"
      style={{ height: height ?? "58vh", minHeight: 240, maxHeight: "90vh" }}
    >
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="拖动调整编辑器高度"
        title="拖动调整高度"
        className="absolute -top-1 left-0 right-0 z-10 flex h-3 cursor-ns-resize touch-none items-center justify-center"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <span className="h-1 w-12 rounded-full bg-zinc-300 dark:bg-zinc-600" />
      </div>
      <div className="h-full min-h-0">{children}</div>
    </div>
  );
}

export default function ChatPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;
  const router = useRouter();
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [openingReport, setOpeningReport] = useState(false);
  const [quitting, setQuitting] = useState(false);
  const [disconnected, setDisconnected] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [ttsAutoPlay, setTtsAutoPlay] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<AnswerComposerHandle>(null);

  const typeBuf = useRef("");
  const typeTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const pendingDone = useRef<StreamDone | null>(null);
  const sawToken = useRef(false);
  const sendingRef = useRef(false);
  const streamingRef = useRef(false);

  useEffect(() => {
    sendingRef.current = sending;
  }, [sending]);
  useEffect(() => {
    streamingRef.current = streaming;
  }, [streaming]);

  useEffect(() => {
    try {
      setTtsAutoPlay(localStorage.getItem(TTS_KEY) === "1");
    } catch {
      setTtsAutoPlay(false);
    }
  }, []);

  const refreshSession = useCallback(async () => {
    try {
      const d = await api<SessionInfo>(`/api/interview/session/${sessionId}`);
      setInfo(d);
      setMsgs(d.history);
      setDisconnected(false);
    } catch {
      setDisconnected(true);
    }
  }, [sessionId]);

  const finishTyping = useCallback(
    (out: StreamDone) => {
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
      window.requestAnimationFrame(() => composerRef.current?.focus());
    },
    [refreshSession]
  );

  const startTypeTimer = useCallback(() => {
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
      if (pendingDone.current) finishTyping(pendingDone.current);
    }, 30);
  }, [finishTyping]);

  const handleStreamToken = useCallback(
    (t: string) => {
      sawToken.current = true;
      setStreaming(true);
      typeBuf.current += t;
      startTypeTimer();
    },
    [startTypeTimer]
  );

  const handleStreamDone = useCallback(
    (raw: StreamDone) => {
      if (sawToken.current) {
        pendingDone.current = raw;
        if (!typeBuf.current) finishTyping(raw);
        return;
      }
      setSending(false);
      setStreaming(false);
      setMsgs((m) => [...m, { role: "interviewer", text: raw.message }]);
      void refreshSession();
      window.requestAnimationFrame(() => composerRef.current?.focus());
    },
    [finishTyping, refreshSession]
  );

  const handleStreamError = useCallback(
    (msg: string) => {
      setSending(false);
      setStreaming(false);
      setDisconnected(true);
      alert(msg || "发送失败，请重试");
      void refreshSession();
    },
    [refreshSession]
  );

  const wsEnabled =
    !!info && info.status === "active" && info.stage !== "FINISHED" && info.stage !== "SUMMARIZING";

  const { resync, sendAnswer } = useInterviewWebSocket(
    sessionId,
    {
      onOpen: () => {
        setWsConnected(true);
        setDisconnected(false);
      },
      onClose: () => {
        setWsConnected(false);
        if (wsEnabled && !sendingRef.current && !streamingRef.current) {
          setDisconnected(true);
        }
      },
      onSnapshot: (data) => {
        if (sendingRef.current || streamingRef.current) return;
        setInfo(data as SessionInfo);
        setMsgs(data.history as ChatMsg[]);
        setDisconnected(false);
      },
      onToken: handleStreamToken,
      onDone: (data) => handleStreamDone(data),
      onError: handleStreamError,
    },
    wsEnabled
  );

  useEffect(() => {
    return () => {
      if (typeTimer.current) clearInterval(typeTimer.current);
    };
  }, []);

  function toggleTts() {
    setTtsAutoPlay((v) => {
      const next = !v;
      try {
        localStorage.setItem(TTS_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  function openReport() {
    if (openingReport) return;
    setOpeningReport(true);
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
        setDisconnected(false);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          router.replace("/login");
        } else {
          setLoadError(e instanceof Error ? e.message : "加载失败");
          setDisconnected(true);
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
    if (!info || info.status !== "active" || info.stage === "FINISHED") return;
    if (wsConnected) return;
    const id = window.setInterval(() => {
      void refreshSession();
    }, 20000);
    return () => window.clearInterval(id);
  }, [info?.status, info?.stage, refreshSession, wsConnected]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, streaming, info?.current_coding]);

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
    if (!text || sending || streaming) return;
    setInput("");
    setSending(true);
    sawToken.current = false;
    typeBuf.current = "";
    pendingDone.current = null;
    if (typeTimer.current) {
      clearInterval(typeTimer.current);
      typeTimer.current = null;
    }
    setMsgs((m) => [...m, { role: "candidate", text }]);
    try {
      if (sendAnswer(text)) return;

      await streamPost(
        `/api/interview/session/${sessionId}/answer/stream`,
        { text },
        {
          onToken: handleStreamToken,
          onDone: (raw) => handleStreamDone(raw as StreamDone),
          onError: (msg) =>
            handleStreamError(typeof msg === "string" ? msg : "发送失败，请重试"),
        }
      );
    } catch (e) {
      if (typeTimer.current) clearInterval(typeTimer.current);
      typeTimer.current = null;
      pendingDone.current = null;
      setStreaming(false);
      setSending(false);
      setDisconnected(true);
      alert(e instanceof Error ? e.message : "发送失败，请重试");
      void refreshSession();
    }
  }

  async function onCodingSubmitted(_judge: unknown, _review: unknown, message: string) {
    setMsgs((m) => [...m, { role: "interviewer", text: message, kind: "coding" }]);
    try {
      const d = await api<SessionInfo>(`/api/interview/session/${sessionId}`);
      setInfo(d);
      setMsgs(d.history);
    } catch {
      setDisconnected(true);
    }
  }

  const showCoding = info?.current_coding && info.stage === "ASKING";
  const isSummarizing = info?.stage === "SUMMARIZING";
  const isActive =
    info?.status === "active" && info?.stage !== "FINISHED" && info?.stage !== "SUMMARIZING";
  const isAbandoned = info?.status === "abandoned";

  return (
    <div className="relative flex h-full min-h-0 flex-1 flex-col bg-zinc-50/60 dark:bg-zinc-950/40">
      <DisconnectOverlay
        visible={disconnected && isActive}
        onRetry={() => {
          resync();
          void refreshSession();
        }}
      />

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
        <div className="flex items-center gap-2">
          {isAbandoned ? <Badge tone="amber">已中途退出</Badge> : null}
          {!info ? <span className="text-xs text-zinc-400">加载中…</span> : null}
        </div>
        <div className="flex items-center gap-3">
          {isActive ? (
            <button
              type="button"
              onClick={quitInterview}
              disabled={quitting || sending || streaming}
              className="text-sm text-zinc-500 hover:text-red-600 disabled:opacity-40"
            >
              {quitting ? "退出中…" : "中途退出"}
            </button>
          ) : null}
          <Link href="/interview/new" className="text-sm text-zinc-500 hover:text-zinc-900">
            新建面试
          </Link>
        </div>
      </div>

      {info && !isAbandoned ? (
        <InterviewStatusBar
          stage={info.stage}
          roundsUsed={info.rounds_used}
          totalRounds={info.total_rounds}
          topicCount={info.topics?.length}
          disconnected={disconnected}
          ttsAutoPlay={ttsAutoPlay}
          onToggleTts={toggleTts}
        />
      ) : null}

      <div className="flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto w-full max-w-2xl">
          {loadError ? <ErrorBanner message={loadError} onRetry={load} /> : null}
          <MessageTimeline messages={msgs} ttsAutoPlay={ttsAutoPlay} />
          {sending && !streaming ? (
            <div className="mt-3 flex items-center gap-2 rounded-2xl border border-zinc-200 bg-white px-3.5 py-2.5 text-xs text-zinc-500 shadow-sm">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
              {isSummarizing || (info && info.rounds_used >= info.total_rounds)
                ? "正在汇总面试报告，请稍候…"
                : "正在评估你的回答，准备下一问…"}
            </div>
          ) : null}
          {isSummarizing && !sending && !streaming ? (
            <div className="mt-3 flex items-center gap-2 rounded-2xl border border-amber-100 bg-amber-50/80 px-3.5 py-2.5 text-xs text-amber-800">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
              正在汇总你的表现并生成报告…
            </div>
          ) : null}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="border-t border-zinc-200/80 bg-white/80 p-4 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/80">
        {info?.status === "finished" || info?.stage === "FINISHED" || isAbandoned ? (
          <div className="flex flex-wrap items-center justify-center gap-3">
            <span className="inline-flex items-center gap-1.5 text-sm text-zinc-500">
              <IconSparkles className="h-4 w-4 text-sky-500" />
              {isAbandoned ? "本场已中途退出" : "面试已结束"}
            </span>
            {!isAbandoned ? (
              <button
                type="button"
                onClick={openReport}
                disabled={openingReport}
                className="rounded-xl bg-gradient-to-r from-sky-600 to-emerald-600 px-6 py-2 text-sm font-medium text-white shadow-md disabled:opacity-70"
              >
                {openingReport ? "正在打开报告…" : "查看面试报告"}
              </button>
            ) : (
              <Link
                href="/interview/new"
                className="rounded-xl bg-gradient-to-r from-sky-600 to-emerald-600 px-6 py-2 text-sm font-medium text-white shadow-md"
              >
                再开一场
              </Link>
            )}
          </div>
        ) : showCoding && info.current_coding ? (
          <ResizableCodingFrame>
            <CodeEditor
              key={`${info.current_coding.slug}-${info.current_coding.templates_by_mode ? "v2" : "v1"}`}
              sessionId={sessionId}
              problem={info.current_coding}
              onSubmitted={onCodingSubmitted}
            />
          </ResizableCodingFrame>
        ) : (
          <div className="mx-auto max-w-2xl">
            <AnswerComposer
              ref={composerRef}
              value={input}
              onChange={setInput}
              onSend={send}
              disabled={!isActive}
              sending={sending || streaming}
            />
          </div>
        )}
      </div>
    </div>
  );
}
