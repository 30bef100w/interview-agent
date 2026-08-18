"use client";

import { useRef, useState } from "react";

import { api, getToken } from "@/lib/api";

type Props = {
  onTranscribed: (text: string) => void;
};

export default function RecorderButton({ onTranscribed }: Props) {
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  async function toggle() {
    if (recording) {
      mediaRef.current?.stop();
      return;
    }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream, { mimeType: "audio/webm" });
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        void sendAudio();
      };
      mediaRef.current = rec;
      rec.start();
      setRecording(true);
    } catch {
      setError("无法访问麦克风，请检查浏览器权限");
    }
  }

  async function sendAudio() {
    if (chunksRef.current.length === 0) return;
    setRecording(false);
    setTranscribing(true);
    setError(null);
    const blob = new Blob(chunksRef.current, { type: "audio/webm" });
    if (blob.size < 1024) {
      setTranscribing(false);
      setError("录音太短，请再试一次");
      return;
    }
    const form = new FormData();
    form.append("file", blob, "record.webm");
    try {
      const res = await api<{ text: string }>("/api/voice/transcribe", {
        method: "POST",
        body: form,
      });
      onTranscribed(res.text);
    } catch (e) {
      setError(e instanceof Error ? e.message : "转写失败，请改用文字输入");
    }
    setTranscribing(false);
  }

  return (
    <div className="flex flex-col items-center gap-1">
      <button
        onClick={toggle}
        disabled={transcribing}
        title={recording ? "点击停止录音" : "点击开始录音说话"}
        className={`flex h-11 w-11 items-center justify-center rounded-full text-white shadow-md transition-colors disabled:opacity-50 ${
          recording
            ? "animate-pulse bg-red-600 shadow-red-600/30"
            : "bg-sky-600 shadow-sky-600/25 hover:bg-sky-500"
        }`}
      >
        {transcribing ? (
          <span className="text-xs">…</span>
        ) : recording ? (
          <span className="block h-3.5 w-3.5 rounded-sm bg-white" />
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z" />
          </svg>
        )}
      </button>
      <span className="text-xs text-zinc-400">
        {transcribing ? "转写中…" : recording ? "录音中，点一下结束" : "语音回答"}
      </span>
      {error && <span className="text-xs text-red-600">{error}</span>}
    </div>
  );
}
