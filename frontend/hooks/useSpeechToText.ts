"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type SpeechError =
  | "not-allowed"
  | "no-speech"
  | "audio-capture"
  | "network"
  | "aborted"
  | "service-not-allowed"
  | "generic";

const MAX_NO_SPEECH = 5;

type RecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: {
    length: number;
    [i: number]: { isFinal: boolean; 0: { transcript: string } };
  };
};

function getCtor(): (new () => RecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => RecognitionLike;
    webkitSpeechRecognition?: new () => RecognitionLike;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

type Options = {
  lang?: string;
  onInterim?: (text: string) => void;
  onFinal?: (text: string) => void;
};

export function useSpeechToText({ lang = "zh-CN", onInterim, onFinal }: Options) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<SpeechError | null>(null);

  const recRef = useRef<RecognitionLike | null>(null);
  const shouldListen = useRef(false);
  const noSpeechCount = useRef(0);
  const finalsRef = useRef("");
  const onInterimRef = useRef(onInterim);
  const onFinalRef = useRef(onFinal);
  onInterimRef.current = onInterim;
  onFinalRef.current = onFinal;

  useEffect(() => {
    setSupported(!!getCtor());
  }, []);

  const emitLive = useCallback((interim: string) => {
    const live = `${finalsRef.current}${interim}`.trim();
    onInterimRef.current?.(live);
  }, []);

  const restart = useCallback(() => {
    const rec = recRef.current;
    if (!rec || !shouldListen.current) return;
    try {
      rec.start();
    } catch {
      /* already started */
    }
  }, []);

  const start = useCallback(() => {
    const Ctor = getCtor();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = lang;
    rec.continuous = true;
    rec.interimResults = true;
    finalsRef.current = "";
    noSpeechCount.current = 0;
    shouldListen.current = true;
    recRef.current = rec;

    rec.onresult = (ev) => {
      noSpeechCount.current = 0;
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
        const piece = ev.results[i][0]?.transcript || "";
        if (ev.results[i].isFinal) finalsRef.current += piece;
        else interim += piece;
      }
      emitLive(interim);
      if (!interim && finalsRef.current) onFinalRef.current?.(finalsRef.current.trim());
    };

    rec.onerror = (ev) => {
      if (ev.error === "aborted" || ev.error === "no-speech") return;
      if (ev.error === "not-allowed") setError("not-allowed");
      else if (ev.error === "network") setError("network");
      else setError("generic");
    };

    rec.onend = () => {
      if (!shouldListen.current) {
        setListening(false);
        const finalText = finalsRef.current.trim();
        if (finalText) onFinalRef.current?.(finalText);
        return;
      }
      noSpeechCount.current += 1;
      if (noSpeechCount.current > MAX_NO_SPEECH) {
        shouldListen.current = false;
        setListening(false);
        setError("no-speech");
        return;
      }
      restart();
    };

    rec.start();
    setListening(true);
    setError(null);
  }, [emitLive, lang, restart]);

  const stop = useCallback(() => {
    shouldListen.current = false;
    try {
      recRef.current?.stop();
    } catch {
      /* ignore */
    }
    setListening(false);
    const finalText = finalsRef.current.trim();
    if (finalText) onFinalRef.current?.(finalText);
  }, []);

  useEffect(() => {
    return () => {
      shouldListen.current = false;
      try {
        recRef.current?.abort();
      } catch {
        /* ignore */
      }
    };
  }, []);

  return { supported, listening, error, start, stop, clearError: () => setError(null) };
}
