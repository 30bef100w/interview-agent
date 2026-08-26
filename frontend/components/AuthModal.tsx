"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Logo } from "@/components/ui";
import { api, getToken, setToken } from "@/lib/api";
import { loadRememberedLogin, saveRememberedLogin } from "@/lib/auth-storage";

type Mode = "login" | "register";

const INPUT_CLS =
  "h-11 w-full rounded-xl border border-zinc-200 bg-white px-3.5 text-sm text-zinc-900 placeholder-zinc-400 outline-none transition-all focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20";

export default function AuthModal({
  open,
  mode: initialMode = "login",
  onClose,
  onModeChange,
}: {
  open: boolean;
  mode?: Mode;
  onClose: () => void;
  onModeChange?: (m: Mode) => void;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open) {
      setMode(initialMode);
      setError("");
      const saved = loadRememberedLogin();
      if (saved) {
        setUsername(saved.username);
        setPassword(saved.password);
        setRemember(true);
      }
    }
  }, [open, initialMode]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  function switchMode(m: Mode) {
    setMode(m);
    setError("");
    onModeChange?.(m);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (mode === "register") {
      if (username.trim().length < 2) {
        setError("用户名至少 2 位");
        return;
      }
      if (password.length < 6) {
        setError("密码至少 6 位");
        return;
      }
    }
    setLoading(true);
    try {
      const path = mode === "login" ? "/api/auth/login" : "/api/auth/register";
      const res = await api<{
        access_token: string;
        user?: { username: string; is_admin?: boolean; platform_quota?: number };
      }>(path, {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setToken(res.access_token);
      localStorage.setItem("username", res.user?.username || username);
      localStorage.setItem("is_admin", res.user?.is_admin ? "1" : "0");
      if (mode === "login") {
        saveRememberedLogin(username, password, remember);
      }
      onClose();
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : mode === "login" ? "登录失败" : "注册失败");
    } finally {
      setLoading(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <button
        type="button"
        aria-label="关闭"
        className="absolute inset-0 bg-slate-900/35 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        className="animate-fade-up relative z-10 w-full max-w-md overflow-hidden rounded-3xl border border-sky-100/80 bg-white p-8 shadow-2xl shadow-sky-900/10"
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 flex h-8 w-8 items-center justify-center rounded-full text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-700"
          aria-label="关闭弹窗"
        >
          ✕
        </button>
        <div className="mb-6 flex justify-center">
          <Logo />
        </div>
        <h2 className="text-center text-xl font-semibold text-slate-900">
          {mode === "login" ? "欢迎回来" : "创建账号"}
        </h2>
        <p className="mt-1.5 text-center text-sm text-zinc-500">
          {mode === "login" ? "登录后继续你的面试训练" : "注册即用，一分钟开启模拟面试"}
        </p>
        <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-3.5">
          <input
            type="text"
            placeholder="用户名"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoFocus
            className={INPUT_CLS}
          />
          <input
            type="password"
            placeholder="密码"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className={INPUT_CLS}
          />
          {mode === "login" ? (
            <label className="flex cursor-pointer items-center gap-2 text-sm text-zinc-600">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="h-4 w-4 rounded border-zinc-300 text-sky-600 focus:ring-sky-500"
              />
              记住密码
            </label>
          ) : null}
          {error && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="mt-1 h-11 rounded-full bg-sky-600 text-sm font-medium text-white shadow-sm shadow-sky-600/25 transition hover:bg-sky-500 disabled:opacity-50"
          >
            {loading ? (mode === "login" ? "登录中…" : "注册中…") : mode === "login" ? "登录" : "注册"}
          </button>
        </form>
        <p className="mt-5 text-center text-sm text-zinc-500">
          {mode === "login" ? (
            <>
              还没有账号？{" "}
              <button
                type="button"
                onClick={() => switchMode("register")}
                className="font-medium text-sky-700 hover:text-sky-600"
              >
                免费注册
              </button>
            </>
          ) : (
            <>
              已有账号？{" "}
              <button
                type="button"
                onClick={() => switchMode("login")}
                className="font-medium text-sky-700 hover:text-sky-600"
              >
                去登录
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
