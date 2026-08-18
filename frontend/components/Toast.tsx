"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type ToastTone = "ok" | "err" | "info";

type ToastItem = {
  id: number;
  message: string;
  tone: ToastTone;
};

type ToastApi = {
  push: (message: string, tone?: ToastTone) => void;
  ok: (message: string) => void;
  err: (message: string) => void;
  info: (message: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback((message: string, tone: ToastTone = "info") => {
    const id = nextId++;
    setItems((prev) => [...prev, { id, message, tone }]);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, 3200);
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      push,
      ok: (m) => push(m, "ok"),
      err: (m) => push(m, "err"),
      info: (m) => push(m, "info"),
    }),
    [push]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-20 left-1/2 z-[80] flex w-[min(92vw,24rem)] -translate-x-1/2 flex-col gap-2 md:bottom-6">
        {items.map((t) => (
          <div
            key={t.id}
            className={`animate-fade-up rounded-xl border px-4 py-2.5 text-sm shadow-lg backdrop-blur ${
              t.tone === "ok"
                ? "border-emerald-200 bg-emerald-50/95 text-emerald-800"
                : t.tone === "err"
                  ? "border-red-200 bg-red-50/95 text-red-700"
                  : "border-sky-100 bg-white/95 text-slate-700"
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    return {
      push: () => {},
      ok: () => {},
      err: () => {},
      info: () => {},
    };
  }
  return ctx;
}
