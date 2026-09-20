"use client";

import { forwardRef, useImperativeHandle, useRef, useState } from "react";

import { IconSend } from "@/components/ui";
import { getToken } from "@/lib/api";
import { canUseMicrophone, micBlockedMessage } from "@/lib/mic";
import { useSpeechToText } from "@/hooks/useSpeechToText";

export type AnswerComposerHandle = {
  focus: () => void;
};

type Props = {
  value: string;
  onChange: (text: string) => void;
  onSend: () => void;
  disabled?: boolean;
  sending?: boolean;
  voiceEnabled?: boolean;
};

const SPEECH_HINT: Record<string, string> = {
  "not-allowed": "请允许麦克风权限",
  "no-speech": "未检测到语音，请再试",
  network: "语音识别网络异常",
  generic: "语音识别失败",
};

const AnswerComposer = forwardRef<AnswerComposerHandle, Props>(function AnswerComposer(
  { value, onChange, onSend, disabled = false, sending = false, voiceEnabled = false },
  ref
) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const speechActive = useRef(false);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const [whisperBusy, setWhisperBusy] = useState(false);
  const [whisperHint, setWhisperHint] = useState("");

  useImperativeHandle(ref, () => ({
    focus: () => {
      textareaRef.current?.focus();
    },
  }));

  const { listening, error, start, stop, clearError } = useSpeechToText({
    onInterim: (live) => {
      if (speechActive.current) onChange(live);
    },
    onFinal: (final) => {
      if (speechActive.current) onChange(final);
    },
  });

  function toggleVoice() {
    clearError();
    setWhisperHint("");
    if (!canUseMicrophone()) {
      setWhisperHint(micBlockedMessage());
      return;
    }
    if (listening) {
      stop();
      speechActive.current = false;
      return;
    }
    speechActive.current = true;
    start();
  }

  async function startWhisperRecord() {
    if (whisperBusy || disabled || sending) return;
    setWhisperHint("");
    clearError();
    if (!canUseMicrophone()) {
      setWhisperHint(micBlockedMessage());
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream, { mimeType: "audio/webm" });
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        if (!blob.size) {
          setWhisperHint("录音为空");
          return;
        }
        setWhisperBusy(true);
        try {
          const fd = new FormData();
          fd.append("file", blob, "answer.webm");
          const res = await fetch(
            `${process.env.NEXT_PUBLIC_API_BASE || ""}/api/voice/transcribe?prompt=${encodeURIComponent("技术面试口语回答")}`,
            {
              method: "POST",
              headers: {
                Authorization: `Bearer ${getToken() || ""}`,
              },
              body: fd,
            }
          );
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error((err as { detail?: string }).detail || "识别失败");
          }
          const data = (await res.json()) as { text?: string };
          const text = (data.text || "").trim();
          if (!text) {
            setWhisperHint("未识别到内容");
            return;
          }
          const prefix = value.trim() ? `${value.trim()} ` : "";
          onChange(prefix + text);
          setWhisperHint("Whisper 识别完成");
        } catch (e) {
          setWhisperHint(e instanceof Error ? e.message : "Whisper 识别失败");
        } finally {
          setWhisperBusy(false);
        }
      };
      mediaRef.current = rec;
      rec.start();
      setWhisperHint("录音中… 再点一次结束并识别");
      setTimeout(() => {
        if (rec.state === "recording") rec.stop();
      }, 60000);
    } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      if (name === "NotAllowedError" || name === "PermissionDeniedError") {
        setWhisperHint("麦克风权限被拒绝，请在浏览器地址栏允许后重试");
      } else {
        setWhisperHint(micBlockedMessage());
      }
    }
  }

  function stopWhisperRecord() {
    const rec = mediaRef.current;
    if (rec && rec.state === "recording") rec.stop();
  }

  return (
    <div
      className="relative z-20 w-full rounded-2xl border border-zinc-200 bg-white p-3 shadow-sm dark:border-zinc-700 dark:bg-zinc-900"
      onMouseDown={(e) => {
        const el = e.target as HTMLElement;
        if (el.closest("button, textarea, a, input")) return;
        e.preventDefault();
        textareaRef.current?.focus();
      }}
    >
      <textarea
        ref={textareaRef}
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
        placeholder={voiceEnabled ? "输入回答，或点麦克风实时转写 / Whisper 录音识别…" : "输入回答，Enter 发送"}
        className="relative z-10 w-full resize-none bg-white text-sm text-zinc-900 caret-zinc-900 outline-none placeholder:text-zinc-400 [transform:translateZ(0)] dark:bg-zinc-900 dark:text-zinc-50 dark:caret-zinc-50"
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {voiceEnabled ? (
            <>
              {canUseMicrophone() ? (
                <button
                  type="button"
                  onClick={toggleVoice}
                  disabled={disabled || sending || whisperBusy}
                  className={`flex h-9 w-9 items-center justify-center rounded-full text-white transition-colors disabled:opacity-40 ${
                    listening ? "animate-pulse bg-red-500" : "bg-sky-600 hover:bg-sky-500"
                  }`}
                  title={listening ? "停止实时转写" : "浏览器实时语音（Web Speech）"}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z" />
                  </svg>
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => {
                  if (whisperHint === "录音中… 再点一次结束并识别") stopWhisperRecord();
                  else startWhisperRecord();
                }}
                disabled={disabled || sending || listening || !canUseMicrophone()}
                className="rounded-lg border border-zinc-200 px-2 py-1 text-[11px] text-zinc-600 hover:border-sky-300 hover:text-sky-700 disabled:opacity-40 dark:border-zinc-600 dark:text-zinc-300"
                title={
                  canUseMicrophone()
                    ? "服务端 Whisper 识别（对标 Gua 上传转写兜底）"
                    : micBlockedMessage()
                }
              >
                {whisperBusy ? "识别中…" : "Whisper"}
              </button>
              {listening ? (
                <span className="animate-pulse text-xs text-red-500">实时转写中…</span>
              ) : canUseMicrophone() ? (
                <span className="text-xs text-zinc-400">Web Speech / Whisper 双路径</span>
              ) : (
                <span className="text-xs text-amber-600">语音需 HTTPS，当前请用文字输入</span>
              )}
              {error ? (
                <span className="text-xs text-red-500">{SPEECH_HINT[error] || error}</span>
              ) : null}
              {whisperHint ? <span className="text-xs text-sky-600">{whisperHint}</span> : null}
            </>
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
});

export default AnswerComposer;
