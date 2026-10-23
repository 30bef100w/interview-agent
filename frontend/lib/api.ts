export const API_BASE = (() => {
  const configured = process.env.NEXT_PUBLIC_API_BASE;
  if (typeof window !== "undefined") {
    // 浏览器同源 /api（Next rewrite 或 Nginx 反代）
    if (configured) return configured.replace(/\/$/, "");
    return "";
  }
  if (configured !== undefined) {
    return configured.replace(/\/$/, "");
  }
  return "http://localhost:8001";
})();

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

export function setToken(token: string) {
  localStorage.setItem("token", token);
}

export function clearToken() {
  localStorage.removeItem("token");
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function errorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (!item || typeof item !== "object") return "";
      const loc = Array.isArray(item.loc) ? item.loc.filter((v: unknown) => v !== "body").join(".") : "";
      return typeof item.msg === "string" ? `${loc ? `${loc}：` : ""}${item.msg}` : "";
    }).filter(Boolean);
    if (messages.length) return messages.join("；");
  }
  return fallback;
}

/** Browser-only namespacing, not authorization. Never use a token itself as a storage key. */
export function userStorageKey(name: string): string {
  try {
    const token = getToken();
    if (!token) return `${name}:anonymous`;
    const encoded = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(encoded));
    if (typeof payload.sub === "string" && /^\d+$/.test(payload.sub)) return `${name}:user:${payload.sub}`;
  } catch {}
  return `${name}:anonymous`;
}

export function newSubmissionId(): string {
  // randomUUID is unavailable on plain HTTP; getRandomValues still works there.
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  if (globalThis.crypto?.getRandomValues) {
    return Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, "0")).join("");
  }
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isForm = options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (!isForm) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const body = await res.json();
      detail = errorDetail(body.detail, detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}
