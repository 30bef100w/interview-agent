"use client";

import { useEffect, useRef, useState } from "react";

import { API_BASE, getToken } from "@/lib/api";

type Props = {
  text: string;
  autoPlay?: boolean;
};

export default function InterviewAudioPlayer({ text, autoPlay = false }: Props) {
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [failed, setFailed] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastText = useRef("");

  async function play() {
    if (!text.trim() || playing) return;
    setFailed(false);
    try {
      const token = getToken();
      const res = await fetch(
        `${API_BASE}/api/voice/tts?text=${encodeURIComponent(text.slice(0, 500))}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} }
      );
      if (!res.ok) throw new Error("tts failed");
      const blob = await res.blob();
      audioRef.current?.pause();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.ontimeupdate = () => {
        if (audio.duration > 0) setProgress((audio.currentTime / audio.duration) * 100);
      };
      audio.onended = () => {
        setPlaying(false);
        setProgress(0);
        URL.revokeObjectURL(url);
      };
      audioRef.current = audio;
      setPlaying(true);
      await audio.play();
    } catch {
      setPlaying(false);
      setFailed(true);
    }
  }

  useEffect(() => {
    if (!autoPlay || !text.trim() || text === lastText.current) return;
    lastText.current = text;
    void play();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, autoPlay]);

  return (
    <div className="mt-2 flex items-center gap-2 rounded-lg border border-zinc-100 bg-zinc-50/80 px-2 py-1.5 dark:border-zinc-800 dark:bg-zinc-800/50">
      <button
        type="button"
        onClick={() => void play()}
        disabled={playing}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
        title={playing ? "播放中" : "播放题目语音"}
      >
        {playing ? (
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
        ) : (
          <svg viewBox="0 0 12 12" className="h-3 w-3" fill="currentColor">
            <path d="M3 1.5v9a0.5 0.5 0 0 0 0.77.42l7-4.5a0.5 0.5 0 0 0 0-.84l-7-4.5A0.5 0.5 0 0 0 3 1.5Z" />
          </svg>
        )}
      </button>
      <div className="relative h-1 flex-1 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-700">
        <div
          className="absolute left-0 top-0 h-full rounded-full bg-sky-500 transition-[width] duration-150"
          style={{ width: `${progress}%` }}
        />
      </div>
      <span className="shrink-0 text-[10px] text-zinc-400">
        {failed ? "语音不可用" : playing ? "播报中" : "TTS"}
      </span>
    </div>
  );
}
