import { setToken } from "@/lib/api";

let pending: Promise<boolean> | null = null;

export function startLocalAdminPreview(): Promise<boolean> {
  if (process.env.NODE_ENV !== "development" || !["127.0.0.1", "localhost", "[::1]"].includes(window.location.hostname)) return Promise.resolve(false);
  if (pending) return pending;
  pending = fetch("/api/local-preview/session", {
    method: "POST", headers: { "x-deepask-preview": "1" }, cache: "no-store",
  }).then(async res => {
    if (res.status === 404) return false;
    if (!res.ok) throw new Error("本地预览连接失败，请确认后端已启动后重试");
    const session = await res.json();
    if (!session.access_token || !session.user?.is_admin) throw new Error("预览账号不可用");
    setToken(session.access_token);
    localStorage.setItem("username", session.user.username);
    localStorage.setItem("is_admin", "1");
    sessionStorage.setItem("deepask-local-preview", "1");
    return true;
  }).finally(() => { pending = null; });
  return pending;
}
