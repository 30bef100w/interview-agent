"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { canUseMicrophone, micBlockedMessage } from "@/lib/mic";

type Phase = "idle" | "requesting" | "recording" | "transcribing";
type Recording = {
  recorder?: MediaRecorder;
  stream?: MediaStream;
  controller?: AbortController;
  timer?: ReturnType<typeof setTimeout>;
  timeout?: ReturnType<typeof setTimeout>;
};

function release(recording: Recording) {
  clearTimeout(recording.timer);
  clearTimeout(recording.timeout);
  recording.controller?.abort();
  const rec = recording.recorder;
  if (rec) {
    rec.ondataavailable = rec.onstop = rec.onerror = null;
    if (rec.state !== "inactive") {
      try { rec.stop(); } catch { /* already stopped */ }
    }
  }
  recording.stream?.getTracks().forEach(track => track.stop());
}

/** Explicit non-streaming fallback. No uploads happen until the user stops recording. */
export function useRecordedTranscription(onText: (text: string) => void) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [hint, setHint] = useState("");
  const active = useRef<Recording | null>(null);
  const callback = useRef(onText);
  callback.current = onText;

  const cancel = useCallback(() => {
    const recording = active.current;
    active.current = null;
    if (recording) release(recording);
    setPhase("idle");
  }, []);

  const stop = useCallback(() => {
    const recording = active.current;
    if (recording?.recorder?.state !== "recording") return;
    setPhase("transcribing");
    setHint("正在将录音转成文字…");
    clearTimeout(recording.timer);
    recording.recorder.stop();
  }, []);

  const start = useCallback(async () => {
    if (active.current) return;
    setHint("");
    if (!canUseMicrophone()) { setHint(micBlockedMessage()); return; }
    if (typeof MediaRecorder === "undefined") { setHint("当前浏览器不支持录音，请使用文字输入"); return; }
    const recording: Recording = {};
    active.current = recording;
    setPhase("requesting");
    const finish = (message: string) => {
      if (active.current !== recording) return;
      active.current = null;
      release(recording);
      setPhase("idle");
      setHint(message);
    };
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (active.current !== recording) { stream.getTracks().forEach(track => track.stop()); return; }
      recording.stream = stream;
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg"]
        .find(type => MediaRecorder.isTypeSupported(type));
      if (!mime) { finish("当前浏览器没有兼容的录音格式，请使用文字输入"); return; }
      const rec = new MediaRecorder(stream, { mimeType: mime });
      recording.recorder = rec;
      const chunks: Blob[] = [];
      let bytes = 0;
      rec.ondataavailable = event => {
        if (active.current !== recording || !event.data.size) return;
        bytes += event.data.size;
        if (bytes > 10 * 1024 * 1024) { finish("录音超过 10MB，请缩短后重试"); return; }
        chunks.push(event.data);
      };
      rec.onerror = () => finish("录音失败，请检查麦克风后重试");
      rec.onstop = async () => {
        if (active.current !== recording) return;
        clearTimeout(recording.timer);
        stream.getTracks().forEach(track => track.stop());
        const blob = new Blob(chunks, { type: rec.mimeType || mime });
        if (!blob.size) { finish("录音为空，请重新录制"); return; }
        setPhase("transcribing");
        setHint("正在将录音转成文字…");
        const controller = new AbortController();
        recording.controller = controller;
        recording.timeout = setTimeout(() => finish("识别超时，请重试或使用文字输入"), 120000);
        try {
          const form = new FormData();
          const extension = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
          form.append("file", blob, `answer.${extension}`);
          const data = await api<{ text?: string }>("/api/voice/transcribe?prompt=" + encodeURIComponent("技术面试口语回答"), {
            method: "POST", body: form, signal: controller.signal,
          });
          if (active.current !== recording) return;
          const text = (data.text || "").trim();
          if (text) callback.current(text);
          finish(text ? "文字已填入，请确认后发送" : "未识别到内容，请重新录制");
        } catch (cause) {
          finish(cause instanceof Error ? cause.message : "录音识别失败，请重试");
        }
      };
      rec.start(1000);
      setPhase("recording");
      setHint("录音中，点击停止后转文字（最长 60 秒）");
      recording.timer = setTimeout(stop, 60000);
    } catch (cause) {
      const name = cause instanceof DOMException ? cause.name : "";
      finish(name === "NotAllowedError" || name === "PermissionDeniedError"
        ? "麦克风权限被拒绝，请在浏览器地址栏允许后重试"
        : "无法开始录音，请检查麦克风或更换浏览器");
    }
  }, [stop]);

  useEffect(() => () => {
    const recording = active.current;
    active.current = null;
    if (recording) release(recording);
  }, []);

  return { phase, hint, start, stop, cancel, clearHint: () => setHint("") };
}
