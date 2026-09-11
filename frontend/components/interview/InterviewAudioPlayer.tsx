"use client";

import { useEffect, useRef, useState } from "react";

import { fetchTtsBlob, ttsKey } from "@/lib/tts";

type Props = {
  text: string;
  autoPlay?: boolean;
  prefetch?: boolean;
};

export default function InterviewAudioPlayer({ text, autoPlay = false, prefetch = false }: Props) {
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [warming, setWarming] = useState(false);
  const [progress, setProgress] = useState(0);
  const [failed, setFailed] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastAuto = useRef("");
  const urlRef = useRef("");

  function stopAudio() {
    audioRef.current?.pause();
    audioRef.current = null;
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = "";
    }
  }

  async function play() {
    const key = ttsKey(text);
    if (!key || playing || loading) return;
    setFailed(false);
    setLoading(true);
    try {
      const blob = await fetchTtsBlob(key);
      stopAudio();
      const url = URL.createObjectURL(blob);
      urlRef.current = url;
      const audio = new Audio(url);
      audio.ontimeupdate = () => {
        if (audio.duration > 0) setProgress((audio.currentTime / audio.duration) * 100);
      };
      audio.onended = () => {
        setPlaying(false);
        setProgress(0);
        stopAudio();
      };
      audioRef.current = audio;
      setPlaying(true);
      await audio.play();
    } catch {
      setPlaying(false);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!prefetch && !autoPlay) return;
    const key = ttsKey(text);
    if (!key) return;
    setWarming(true);
    void fetchTtsBlob(key)
      .catch(() => {
        setFailed(true);
      })
      .finally(() => setWarming(false));
  }, [text, prefetch, autoPlay]);

  useEffect(() => {
    if (!autoPlay || !text.trim() || ttsKey(text) === lastAuto.current) return;
    lastAuto.current = ttsKey(text);
    void play();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, autoPlay]);

  useEffect(() => () => stopAudio(), []);

  const busy = playing || loading || warming;
  const label = failed ? "语音不可用" : loading || warming ? "合成中" : playing ? "播报中" : "TTS";

  return (
    <div className="mt-2 flex items-center gap-2 rounded-lg border border-zinc-100 bg-zinc-50/80 px-2 py-1.5 dark:border-zinc-800 dark:bg-zinc-800/50">
      <button
        type="button"
        onClick={() => void play()}
        disabled={playing || loading}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
        title={loading || warming ? "正在合成语音…" : playing ? "播放中" : "播放题目语音"}
      >
        {busy ? (
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
      <span className="shrink-0 text-[10px] text-zinc-400">{label}</span>
    </div>
  );
}
