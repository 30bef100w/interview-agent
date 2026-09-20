"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";

/** 生产默认关语音；以 backend `/api/voice/status` 为准。 */
export function useVoiceEnabled(): boolean {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<{ enabled: boolean }>("/api/voice/status")
      .then((row) => {
        if (!cancelled) setEnabled(Boolean(row.enabled));
      })
      .catch(() => {
        if (!cancelled) setEnabled(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return enabled;
}
