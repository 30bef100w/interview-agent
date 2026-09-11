import { API_BASE, getToken } from "@/lib/api";

const blobCache = new Map<string, Blob>();
const inflight = new Map<string, Promise<Blob>>();

export function ttsKey(text: string): string {
  return text.trim().slice(0, 500);
}

export function fetchTtsBlob(text: string): Promise<Blob> {
  const key = ttsKey(text);
  if (!key) return Promise.reject(new Error("empty tts text"));
  const cached = blobCache.get(key);
  if (cached) return Promise.resolve(cached);
  const pending = inflight.get(key);
  if (pending) return pending;

  const req = (async () => {
    const token = getToken();
    const res = await fetch(`${API_BASE}/api/voice/tts?text=${encodeURIComponent(key)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error("tts failed");
    const blob = await res.blob();
    if (!blob.size) throw new Error("tts empty");
    blobCache.set(key, blob);
    return blob;
  })();

  inflight.set(key, req);
  return req.finally(() => {
    inflight.delete(key);
  });
}
