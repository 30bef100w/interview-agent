"use client";

import { useRef } from "react";

import { IconSend } from "@/components/ui";
import { useSpeechToText } from "@/hooks/useSpeechToText";

type Props = {
  value: string;
  onChange: (text: string) => void;
  onSend: () => void;
  disabled?: boolean;
  sending?: boolean;
};

const SPEECH_HINT: Record<string, string> = {
  "not-allowed": "请允许麦克风权限",
  "no-speech": "未检测到语音，请再试",
  network: "语音识别网络异常",
  generic: "语音识别失败",
};

export default function AnswerComposer({
  value,
  onChange,
  onSend,
  disabled = false,
  sending = false,
}: Props) {
  const speechActive = useRef(false);
  const { supported, listening, error, start, stop, clearError } = useSpeechToText({
    onInterim: (live) => {
      if (speechActive.current) onChange(live);
    },
    onFinal: (final) => {
      if (speechActive.current) onChange(final);
    },
  });

  function toggleVoice() {
    clearError();
    if (listening) {
      stop();
      speechActive.current = false;
      return;
    }
    speechActive.current = true;
    start();
  }

  return (
    <div className="w-full rounded-2xl border border-zinc-200 bg-white p-3 shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
      <textarea
        value={value}
        onChange={(e) => {
          speechActive.current = false;
          onChange(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            onSend();
          }
          if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            onSend();
          }
        }}
        rows={3}
        disabled={disabled || sending}
        placeholder="输入回答，或点麦克风实时转写…（Ctrl+Enter 发送）"
        className="w-full resize-none bg-transparent text-sm text-zinc-900 outline-none placeholder:text-zinc-400 dark:text-zinc-50"
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {supported ? (
            <button
              type="button"
              onClick={toggleVoice}
              disabled={disabled || sending}
              className={`flex h-9 w-9 items-center justify-center rounded-full text-white transition-colors disabled:opacity-40 ${
                listening ? "animate-pulse bg-red-500" : "bg-sky-600 hover:bg-sky-500"
              }`}
              title={listening ? "停止录音" : "实时语音转文字"}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z" />
              </svg>
            </button>
          ) : null}
          {listening ? (
            <span className="animate-pulse text-xs text-red-500">实时转写中…</span>
          ) : (
            <span className="text-xs text-zinc-400">支持边说边出字</span>
          )}
          {error ? (
            <span className="text-xs text-red-500">{SPEECH_HINT[error] || error}</span>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onSend}
          disabled={disabled || sending || !value.trim()}
          className="inline-flex items-center gap-1.5 rounded-xl bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-40"
        >
          <IconSend className="h-4 w-4" />
          发送
        </button>
      </div>
    </div>
  );
}
