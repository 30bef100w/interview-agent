"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";

type Props = {
  /** 开始录音时已有的输入，语音结果会接在后面 */
  seedText?: string;
  onTranscribed: (text: string) => void;
};

type SpeechRec = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null;
  onerror: ((ev: { error: string }) => void) | null;
  onend: (() => void) | null;
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: {
    length: number;
    [i: number]: { isFinal: boolean; 0: { transcript: string } };
  };
};

function getSpeechRecognition(): (new () => SpeechRec) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRec;
    webkitSpeechRecognition?: new () => SpeechRec;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export default function RecorderButton({ seedText = "", onTranscribed }: Props) {
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState("语音回答");

  const modeRef = useRef<"speech" | "upload" | null>(null);
  const speechRef = useRef<SpeechRec | null>(null);
  const finalsRef = useRef("");
  const prefixRef = useRef("");
  const stopRequestedRef = useRef(false);

  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    return () => {
      stopRequestedRef.current = true;
      try {
        speechRef.current?.abort();
      } catch {
        /* ignore */
      }
      try {
        mediaRef.current?.stop();
      } catch {
        /* ignore */
      }
    };
  }, []);

  function buildPrefix(seed: string) {
    const s = seed.trimEnd();
    if (!s) return "";
    return /[\s\n]$/.test(seed) ? seed : `${s} `;
  }

  function startSpeechRecognition() {
    const Ctor = getSpeechRecognition();
    if (!Ctor) return false;

    const rec = new Ctor();
    rec.lang = "zh-CN";
    rec.continuous = true;
    rec.interimResults = true;
    finalsRef.current = "";
    prefixRef.current = buildPrefix(seedText);
    stopRequestedRef.current = false;
    speechRef.current = rec;
    modeRef.current = "speech";

    rec.onresult = (ev) => {
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
        const piece = ev.results[i][0]?.transcript || "";
        if (ev.results[i].isFinal) finalsRef.current += piece;
        else interim += piece;
      }
      const live = `${prefixRef.current}${finalsRef.current}${interim}`.trimStart();
      if (live) onTranscribed(live);
      setHint(interim ? "识别中…" : "说话中，点一下结束");
    };

    rec.onerror = (ev) => {
      if (ev.error === "aborted" || ev.error === "no-speech") return;
      if (ev.error === "not-allowed") {
        setError("麦克风权限被拒绝，请在浏览器允许后重试");
        return;
      }
      // 网络类错误时回退到上传转写
      if (ev.error === "network" || ev.error === "service-not-allowed") {
        setError(null);
        void startUploadFallback();
        return;
      }
      setError(`语音识别异常：${ev.error}`);
    };

    rec.onend = () => {
      // continuous 模式有时会自己停；若用户未点停则自动重启
      if (!stopRequestedRef.current && modeRef.current === "speech") {
        try {
          rec.start();
          return;
        } catch {
          /* fall through */
        }
      }
      setRecording(false);
      setHint("语音回答");
      const finalText = `${prefixRef.current}${finalsRef.current}`.trim();
      if (finalText) onTranscribed(finalText);
    };

    rec.start();
    setRecording(true);
    setHint("说话中，可边说边改字");
    return true;
  }

  async function startUploadFallback() {
    modeRef.current = "upload";
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
      setHint("录音中，点一下结束（本地转写）");
    } catch {
      setError("无法访问麦克风，请检查浏览器权限");
      setRecording(false);
    }
  }

  async function sendAudio() {
    if (chunksRef.current.length === 0) return;
    setRecording(false);
    setTranscribing(true);
    setError(null);
    setHint("转写中…");
    const blob = new Blob(chunksRef.current, { type: "audio/webm" });
    if (blob.size < 1024) {
      setTranscribing(false);
      setHint("语音回答");
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
      const text = (res.text || "").trim();
      if (!text) {
        setError("没有识别到内容，请靠近麦克风再说一次");
      } else {
        const merged = `${buildPrefix(seedText)}${text}`.trim();
        onTranscribed(merged);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "转写失败，请改用文字输入");
    }
    setTranscribing(false);
    setHint("语音回答");
  }

  async function toggle() {
    if (recording) {
      stopRequestedRef.current = true;
      if (modeRef.current === "speech") {
        try {
          speechRef.current?.stop();
        } catch {
          /* ignore */
        }
        setRecording(false);
        setHint("语音回答");
        const finalText = `${prefixRef.current}${finalsRef.current}`.trim();
        if (finalText) onTranscribed(finalText);
      } else {
        mediaRef.current?.stop();
      }
      return;
    }

    setError(null);
    if (startSpeechRecognition()) return;
    // Safari / 不支持 Web Speech 时走本地 whisper
    await startUploadFallback();
  }

  return (
    <div className="flex flex-col items-center gap-1">
      <button
        onClick={() => void toggle()}
        disabled={transcribing}
        title={recording ? "点击停止" : "点击开始语音（边说边出字）"}
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
      <span className="max-w-[5.5rem] text-center text-xs text-zinc-400">{hint}</span>
      {error && <span className="max-w-[9rem] text-center text-xs text-red-600">{error}</span>}
    </div>
  );
}
