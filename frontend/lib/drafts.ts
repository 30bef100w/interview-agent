import { userStorageKey } from "@/lib/api";

const TTL_MS = 7 * 24 * 60 * 60 * 1000;

/** Session-scoped storage survives refresh without leaving drafts on disk indefinitely. */
export function loadDraft<T>(name: string): T | null {
  try {
    const key = userStorageKey(`fa_draft:${name}`);
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const record = JSON.parse(raw);
    if (typeof record.at !== "number" || Date.now() - record.at > TTL_MS) {
      sessionStorage.removeItem(key);
      return null;
    }
    return record.value as T;
  } catch { return null; }
}

export function saveDraft(name: string, value: unknown): void {
  try {
    sessionStorage.setItem(userStorageKey(`fa_draft:${name}`), JSON.stringify({ at: Date.now(), value }));
  } catch { /* In-memory editing still works when browser storage is unavailable. */ }
}

export function removeDraft(name: string): void {
  try { sessionStorage.removeItem(userStorageKey(`fa_draft:${name}`)); } catch {}
}
