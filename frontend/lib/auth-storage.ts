const REMEMBER_KEY = "fa_remember_login";

type Remembered = {
  username: string;
};

export function loadRememberedLogin(): Remembered | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(REMEMBER_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    // Delete legacy plaintext credentials before attempting any new write.
    localStorage.removeItem(REMEMBER_KEY);
    if (!data || typeof data.username !== "string" || !data.username) return null;
    const saved: Remembered = { username: data.username };
    localStorage.setItem(REMEMBER_KEY, JSON.stringify(saved));
    return saved;
  } catch {
    try { localStorage.removeItem(REMEMBER_KEY); } catch {}
    return null;
  }
}

export function saveRememberedLogin(username: string, remember: boolean) {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(REMEMBER_KEY);
    if (remember) {
      localStorage.setItem(REMEMBER_KEY, JSON.stringify({ username }));
    }
  } catch {
    /* ignore */
  }
}
