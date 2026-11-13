"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { IconSend } from "@/components/ui";
import { useRecordedTranscription } from "@/hooks/useRecordedTranscription";
import { useSpeechToText, type SpeechError } from "@/hooks/useSpeechToText";
import { canUseMicrophone, micBlockedMessage } from "@/lib/mic";
import { appendSpeechDraft } from "@/lib/speech-draft";

export type AnswerComposerHandle = { focus: () => void };

type Props = {
  value: string;
  onChange: (text: string) => void;
  onSend: () => void;
  disabled?: boolean;
  sending?: boolean;
  voiceEnabled?: boolean;
};

const SPEECH_HINT: Record<SpeechError, string> = {
  "not-allowed": "麦克风权限被拒绝，请在地址栏允许后重试",
  "no-speech": "未检测到语音，已停止，请重试",
  "audio-capture": "无法读取麦克风，请检查设备是否被占用",
  network: "实时识别服务连接失败，可改用“录音转文字”重新录制",
  "service-not-allowed": "浏览器禁止实时识别，可改用“录音转文字”",
  unsupported: "浏览器不支持实时识别，请使用“录音转文字”",
  aborted: "实时识别已中断，请重试",
  generic: "实时识别失败，可改用“录音转文字”重新录制",
};

const AnswerComposer = forwardRef<AnswerComposerHandle, Props>(function AnswerComposer(
  { value, onChange, onSend, disabled = false, sending = false, voiceEnabled = false }, ref
) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const speechActive = useRef(false);
  const speechBase = useRef("");
  const valueRef = useRef(value);
  valueRef.current = value;
  const [microphone, setMicrophone] = useState({ available: false, hint: "正在检查麦克风…" });
  const micAvailable = microphone.available;
  useEffect(() => {
    setMicrophone({ available: canUseMicrophone(), hint: micBlockedMessage() });
  }, []);

  useImperativeHandle(ref, () => ({ focus: () => textareaRef.current?.focus() }));

  function updateDraft(text: string) {
    valueRef.current = text;
    onChange(text);
  }

  const { supported, listening, stopping, error, start, stop, cancel, clearError } = useSpeechToText({
    onInterim: text => {
      if (speechActive.current) updateDraft(appendSpeechDraft(speechBase.current, text));
    },
    onFinal: text => {
      if (speechActive.current) updateDraft(appendSpeechDraft(speechBase.current, text));
      speechActive.current = false;
    },
  });
  const recording = useRecordedTranscription(text => updateDraft(appendSpeechDraft(valueRef.current, text)));
  const voiceBusy = listening || stopping || recording.phase !== "idle";
  const canSend = !disabled && !sending && !voiceBusy && !!value.trim();

  useEffect(() => {
    if (disabled || sending || !voiceEnabled) {
      speechActive.current = false;
      cancel();
      recording.cancel();
    }
  }, [disabled, sending, voiceEnabled, cancel, recording.cancel]);

  function cancelVoice() {
    speechActive.current = false;
    cancel();
    recording.cancel();
    recording.clearHint();
  }

  function toggleVoice() {
    if (disabled || sending || stopping || recording.phase !== "idle") return;
    clearError();
    recording.clearHint();
    if (listening) { stop(); return; }
    if (!micAvailable || !supported) return;
    speechBase.current = valueRef.current;
    speechActive.current = true;
    if (!start()) speechActive.current = false;
  }

  return (
    <div
      className="relative z-20 w-full rounded-2xl border border-zinc-200 bg-white p-3 shadow-sm dark:border-zinc-700 dark:bg-zinc-900"
      onMouseDown={event => {
        const el = event.target as HTMLElement;
        if (el.closest("button, textarea, a, input")) return;
        event.preventDefault();
        textareaRef.current?.focus();
      }}
    >
      <textarea
        ref={textareaRef}
        value={value}
        onChange={event => {
          // Editing takes ownership of the draft; late speech/upload results must not overwrite it.
          cancelVoice();
          updateDraft(event.target.value);
        }}
        onKeyDown={event => {
          if (event.nativeEvent.isComposing || event.keyCode === 229) return;
          if (event.key === "Enter" && (!event.shiftKey || event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            if (canSend) onSend();
          }
        }}
        rows={3}
        disabled={disabled || sending}
        aria-label="回答输入框"
        placeholder={voiceEnabled ? "输入回答，或点击麦克风说话转文字，确认后发送" : "输入回答，Enter 发送"}
        className="relative z-10 w-full resize-none bg-white text-sm text-zinc-900 caret-zinc-900 outline-none placeholder:text-zinc-400 [transform:translateZ(0)] dark:bg-zinc-900 dark:text-zinc-50 dark:caret-zinc-50"
      />
      <div className="mt-2 flex items-end justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {voiceEnabled ? (
            <>
              <button
                type="button"
                onClick={toggleVoice}
                disabled={disabled || sending || stopping || recording.phase !== "idle" || !micAvailable || !supported}
                className={`flex h-9 w-9 items-center justify-center rounded-full text-white transition-colors disabled:opacity-40 ${
                  listening ? "animate-pulse bg-red-500" : "bg-sky-600 hover:bg-sky-500"
                }`}
                aria-label={listening ? "停止实时转文字" : "开始实时转文字"}
                aria-pressed={listening}
                title={!micAvailable ? microphone.hint : !supported ? SPEECH_HINT.unsupported : "实时转文字（可能使用浏览器厂商的在线识别服务）"}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z" />
                </svg>
              </button>
              <button
                type="button"
                onClick={() => {
                  if (recording.phase === "recording") recording.stop();
                  else { clearError(); void recording.start(); }
                }}
                disabled={disabled || sending || listening || stopping || !micAvailable || recording.phase === "requesting" || recording.phase === "transcribing"}
                className="rounded-lg border border-zinc-200 px-2 py-1 text-xs text-zinc-600 hover:border-sky-300 hover:text-sky-700 disabled:opacity-40 dark:border-zinc-600 dark:text-zinc-300"
                title={micAvailable ? "备用方式：录音结束后上传服务器 Whisper 转文字，不是实时识别" : microphone.hint}
              >
                {recording.phase === "recording" ? "停止并转文字" : recording.phase === "transcribing" ? "识别中…" : recording.phase === "requesting" ? "等待麦克风…" : "录音转文字"}
              </button>
              {voiceBusy ? (
                <button type="button" onClick={cancelVoice} className="text-xs text-zinc-500 hover:text-red-500">取消语音</button>
              ) : null}
              <span role="status" aria-live="polite" className="basis-full text-xs text-zinc-500">
                {!micAvailable ? microphone.hint : stopping ? "正在收尾，请稍候…" : listening
                  ? "正在听你说话并转文字… 再点麦克风停止；编辑文字会停止转写（最长 60 秒）"
                  : recording.hint || (!supported ? SPEECH_HINT.unsupported : "说话转文字 → 确认或修改 → 手动发送")}
              </span>
              {error ? <span role="alert" className="basis-full text-xs text-red-500">{SPEECH_HINT[error]}</span> : null}
            </>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => { if (canSend) onSend(); }}
          disabled={!canSend}
          title={voiceBusy ? "请先停止语音，确认文字后再发送" : "发送回答"}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-40"
        >
          <IconSend className="h-4 w-4" />
          发送
        </button>
      </div>
    </div>
  );
});

export default AnswerComposer;
