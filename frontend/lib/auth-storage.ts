const REMEMBER_KEY = "fa_remember_login";

type Remembered = {
  username: string;
  password: string;
};

export function loadRememberedLogin(): Remembered | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(REMEMBER_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as Remembered;
    if (!data.username || !data.password) return null;
    return data;
  } catch {
    return null;
  }
}

export function saveRememberedLogin(username: string, password: string, remember: boolean) {
  if (typeof window === "undefined") return;
  try {
    if (remember) {
      localStorage.setItem(REMEMBER_KEY, JSON.stringify({ username, password }));
    } else {
      localStorage.removeItem(REMEMBER_KEY);
    }
  } catch {
    /* ignore */
  }
}
