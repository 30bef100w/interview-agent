import { API_BASE, getToken } from "@/lib/api";

/** 将 HTTP API 基址转为 WebSocket 基址 */
export function wsBase(): string {
  const base = API_BASE.replace(/\/$/, "");
  if (base.startsWith("https://")) return `wss://${base.slice(8)}`;
  if (base.startsWith("http://")) return `ws://${base.slice(7)}`;
  return `ws://${base}`;
}

export function interviewWsUrl(sessionId: string | number): string {
  const token = encodeURIComponent(getToken() ?? "");
  return `${wsBase()}/ws/interview/${sessionId}?token=${token}`;
}
