"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type SpeechError =
  | "not-allowed" | "no-speech" | "audio-capture" | "network"
  | "aborted" | "service-not-allowed" | "unsupported" | "generic";

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

type SpeechSession = {
  rec: RecognitionLike | null;
  committed: string;
  current: string;
  stopping: boolean;
  emptyEnds: number;
  restartTimer?: ReturnType<typeof setTimeout>;
  stopTimer?: ReturnType<typeof setTimeout>;
  limitTimer?: ReturnType<typeof setTimeout>;
};

function release(session: SpeechSession) {
  clearTimeout(session.restartTimer);
  clearTimeout(session.stopTimer);
  clearTimeout(session.limitTimer);
  if (session.rec) {
    session.rec.onresult = session.rec.onerror = session.rec.onend = null;
    try { session.rec.abort(); } catch { /* already ended */ }
    session.rec = null;
  }
}

/** Browser interim results only update the draft; this hook never sends a message. */
export function useSpeechToText({ lang = "zh-CN", onInterim, onFinal }: Options) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<SpeechError | null>(null);
  const sessionRef = useRef<SpeechSession | null>(null);
  const callbacks = useRef({ onInterim, onFinal });
  callbacks.current = { onInterim, onFinal };

  useEffect(() => { setSupported(!!getCtor()); }, []);

  const finish = useCallback((session: SpeechSession, failure?: SpeechError) => {
    if (sessionRef.current !== session) return;
    sessionRef.current = null;
    const text = `${session.committed}${session.current}`.trim();
    release(session);
    setListening(false);
    setStopping(false);
    if (failure) setError(failure);
    // Retain the last interim hypothesis if the browser never finalizes it.
    if (text) callbacks.current.onFinal?.(text);
  }, []);

  const stop = useCallback(() => {
    const session = sessionRef.current;
    if (!session || session.stopping) return;
    session.stopping = true;
    setStopping(true);
    clearTimeout(session.restartTimer);
    if (!session.rec) { finish(session); return; }
    // Keep accepting final results until onend; stop() is asynchronous.
    session.stopTimer = setTimeout(() => finish(session), 2000);
    try { session.rec.stop(); } catch { finish(session); }
  }, [finish]);

  const cancel = useCallback(() => {
    const session = sessionRef.current;
    sessionRef.current = null;
    if (session) release(session);
    setListening(false);
    setStopping(false);
  }, []);

  const start = useCallback(() => {
    if (sessionRef.current) return false;
    const Ctor = getCtor();
    if (!Ctor) { setError("unsupported"); return false; }
    const Recognition = Ctor;
    const session: SpeechSession = { rec: null, committed: "", current: "", stopping: false, emptyEnds: 0 };
    sessionRef.current = session;
    setError(null);
    setListening(true);
    setStopping(false);

    function launch() {
      if (sessionRef.current !== session || session.stopping) return;
      try {
        const rec = new Recognition();
        session.rec = rec;
        rec.lang = lang;
        rec.continuous = true;
        rec.interimResults = true;
        rec.onresult = (event) => {
          if (sessionRef.current !== session || session.rec !== rec) return;
          // Results are a snapshot for this instance, not append-only deltas.
          let text = "";
          for (let i = 0; i < event.results.length; i += 1) {
            text += event.results[i][0]?.transcript || "";
          }
          session.current = text;
          if (text.trim()) session.emptyEnds = 0;
          callbacks.current.onInterim?.(`${session.committed}${text}`.trim());
        };
        rec.onerror = ({ error: code }) => {
          if (sessionRef.current !== session || session.rec !== rec) return;
          if (code === "no-speech" || (code === "aborted" && session.stopping)) return;
          const known: SpeechError[] = ["not-allowed", "audio-capture", "network", "aborted", "service-not-allowed"];
          // Permission/network failures are terminal, never an automatic retry loop.
          finish(session, known.includes(code as SpeechError) ? code as SpeechError : "generic");
        };
        rec.onend = () => {
          if (sessionRef.current !== session || session.rec !== rec) return;
          rec.onresult = rec.onerror = rec.onend = null;
          session.rec = null;
          if (session.stopping) { finish(session); return; }
          if (!session.current.trim()) session.emptyEnds += 1;
          session.committed += session.current;
          session.current = "";
          if (session.emptyEnds >= 5) { finish(session, "no-speech"); return; }
          // A fresh instance resets browser result indexes on each restart.
          session.restartTimer = setTimeout(launch, 250);
        };
        rec.start();
      } catch (cause) {
        finish(session, cause instanceof DOMException && cause.name === "NotAllowedError" ? "not-allowed" : "generic");
      }
    }

    session.limitTimer = setTimeout(stop, 60000);
    launch();
    return sessionRef.current === session;
  }, [finish, lang, stop]);

  useEffect(() => () => {
    const session = sessionRef.current;
    sessionRef.current = null;
    if (session) release(session);
  }, []);

  return { supported, listening, stopping, error, start, stop, cancel, clearError: () => setError(null) };
}
