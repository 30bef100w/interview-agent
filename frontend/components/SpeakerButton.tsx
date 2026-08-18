"use client";

import { useRef, useState } from "react";

import { API_BASE, getToken } from "@/lib/api";

type Props = {
  text: string;
};

export default function SpeakerButton({ text }: Props) {
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  async function play() {
    if (playing) return;
    setFailed(false);
    try {
      const token = getToken();
      const res = await fetch(
        `${API_BASE}/api/voice/tts?text=${encodeURIComponent(text.slice(0, 500))}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} }
      );
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      audioRef.current?.pause();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => {
        setPlaying(false);
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

  return (
    <button
      onClick={play}
      disabled={playing}
      title="播放语音"
      className={`ml-2 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors disabled:opacity-50 ${
        failed
          ? "border-red-200 text-red-500 dark:border-red-900"
          : "border-zinc-300 text-zinc-500 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
      }`}
    >
      {playing ? (
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-green-500" />
      ) : failed ? (
        "语音不可用"
      ) : (
        <>
          <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M11 5 6.5 9H3v6h3.5L11 19V5Z" strokeLinejoin="round" />
            <path d="M15 9.5a4 4 0 0 1 0 5M17.5 7a7.5 7.5 0 0 1 0 10" strokeLinecap="round" />
          </svg>
          播放
        </>
      )}
    </button>
  );
}
