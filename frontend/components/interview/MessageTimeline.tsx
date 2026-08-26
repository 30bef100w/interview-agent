"use client";

import InterviewAudioPlayer from "@/components/interview/InterviewAudioPlayer";
import MarkdownRenderer from "@/components/MarkdownRenderer";

export type ChatMsg = {
  role: "interviewer" | "candidate";
  text: string;
  streaming?: boolean;
  kind?: "question" | "followup" | "coding" | "hr" | "system";
};

type Props = {
  messages: ChatMsg[];
  ttsAutoPlay?: boolean;
};

function kindLabel(kind?: ChatMsg["kind"]) {
  if (kind === "followup") return "追问";
  if (kind === "coding") return "算法";
  if (kind === "hr") return "HR";
  return null;
}

export default function MessageTimeline({ messages, ttsAutoPlay }: Props) {
  if (messages.length === 0) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-sm text-zinc-400">
        等待面试官开场…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3.5">
      {messages.map((m, i) => {
        const label = m.role === "interviewer" ? kindLabel(m.kind) : null;
        return (
          <div
            key={`${i}-${m.role}-${m.text.slice(0, 24)}`}
            className={`flex items-end gap-2 ${m.role === "candidate" ? "justify-end" : "justify-start"}`}
          >
            {m.role === "interviewer" && (
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-emerald-600 text-[10px] font-bold text-white shadow-sm">
                面
              </div>
            )}
            <div
              className={`max-w-[88%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed shadow-sm ${
                m.role === "candidate"
                  ? "rounded-br-md bg-gradient-to-br from-sky-600 to-emerald-600 text-white"
                  : "rounded-bl-md border border-zinc-200/80 bg-white text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100"
              }`}
            >
              {label ? (
                <span className="mb-1 inline-block rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-medium text-sky-700 dark:bg-sky-950 dark:text-sky-300">
                  {label}
                </span>
              ) : null}
              <div className={`${m.streaming ? "streaming-cursor" : ""}`}>
                {m.role === "interviewer" ? (
                  m.streaming ? (
                    <div className="whitespace-pre-wrap">{m.text}</div>
                  ) : (
                    <MarkdownRenderer content={m.text || "…"} />
                  )
                ) : (
                  <div className="whitespace-pre-wrap">{m.text}</div>
                )}
              </div>
              {m.role === "interviewer" && !m.streaming && m.text ? (
                <InterviewAudioPlayer text={m.text} autoPlay={ttsAutoPlay} />
              ) : null}
            </div>
            {m.role === "candidate" && (
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-200 text-zinc-500 dark:bg-zinc-800">
                <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <circle cx="12" cy="8" r="3.5" />
                  <path d="M5 20a7 7 0 0 1 14 0" strokeLinecap="round" />
                </svg>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
