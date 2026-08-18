"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import OnboardingModal from "@/components/OnboardingModal";
import { ToastProvider } from "@/components/Toast";
import { IconChart, IconHistory, IconMic, IconReport, IconSliders, IconTarget, IconUpload, Logo } from "@/components/ui";
import { api, clearToken, getToken } from "@/lib/api";
import { unreadCount } from "@/lib/notifications";

type NavItem = { href: string; label: string; icon: ReactNode };

const NAV: NavItem[] = [
  { href: "/dashboard", label: "工作台", icon: <IconTarget className="h-4.5 w-4.5" /> },
  { href: "/interview/new", label: "开始面试", icon: <IconMic className="h-4.5 w-4.5" /> },
  { href: "/resume/upload", label: "我的简历", icon: <IconUpload className="h-4.5 w-4.5" /> },
  { href: "/history", label: "面试记录", icon: <IconHistory className="h-4.5 w-4.5" /> },
  { href: "/growth", label: "成长档案", icon: <IconChart className="h-4.5 w-4.5" /> },
  { href: "/settings", label: "模型设置", icon: <IconSliders className="h-4.5 w-4.5" /> },
  { href: "/usage", label: "用量查询", icon: <IconReport className="h-4.5 w-4.5" /> },
];

function usernameOf(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem("username");
  } catch {
    return null;
  }
}

function isAdminOf(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return localStorage.getItem("is_admin") === "1";
  } catch {
    return false;
  }
}

function IconBell({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M6 9a6 6 0 1 1 12 0c0 7 3 7 3 7H3s3 0 3-7" strokeLinecap="round" />
      <path d="M10 19a2 2 0 0 0 4 0" strokeLinecap="round" />
    </svg>
  );
}

function IconHelp({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1.9-1.1 1.8V14" strokeLinecap="round" />
      <circle cx="12" cy="17" r="0.8" fill="currentColor" stroke="none" />
    </svg>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [username, setUsername] = useState<string | null>(() => usernameOf());
  const [isAdmin, setIsAdmin] = useState(() => isAdminOf());
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (pathname === "/" || pathname === "/login" || pathname === "/register") return;
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api<{ username: string; is_admin?: boolean }>("/api/auth/me")
      .then((me) => {
        localStorage.setItem("username", me.username);
        localStorage.setItem("is_admin", me.is_admin ? "1" : "0");
        setUsername(me.username);
        setIsAdmin(Boolean(me.is_admin));
      })
      .catch(() => {
        clearToken();
        localStorage.removeItem("username");
        localStorage.removeItem("is_admin");
        router.replace("/login");
      });
  }, [router, pathname]);

  useEffect(() => {
    const sync = () => setUnread(unreadCount());
    sync();
    window.addEventListener("fa-notifications", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("fa-notifications", sync);
      window.removeEventListener("storage", sync);
    };
  }, [pathname]);

  function logout() {
    clearToken();
    localStorage.removeItem("username");
    localStorage.removeItem("is_admin");
    router.replace("/");
  }

  const bare =
    pathname === "/" ||
    pathname === "/login" ||
    pathname === "/register" ||
    pathname.startsWith("/admin");
  const fullscreen = pathname.startsWith("/interview/") && pathname !== "/interview/new";
  const navItems = NAV;

  if (bare || fullscreen) {
    return (
      <ToastProvider>
        <div className="flex h-full min-h-0 flex-1 flex-col">{children}</div>
      </ToastProvider>
    );
  }

  return (
    <ToastProvider>
      <div className="flex min-h-full flex-1 flex-col bg-gradient-to-br from-sky-50/40 via-white to-sky-50/30 md:flex-row">
        <div className="flex items-center justify-between border-b border-sky-100/80 bg-white/90 px-4 py-3 backdrop-blur md:hidden">
          <Link href="/dashboard">
            <Logo size="sm" />
          </Link>
          <div className="flex items-center gap-3">
            <Link href="/notifications" className="relative text-slate-500">
              <IconBell className="h-5 w-5" />
              {unread > 0 && (
                <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-sky-600 px-1 text-[10px] text-white">
                  {unread > 9 ? "9+" : unread}
                </span>
              )}
            </Link>
            <button type="button" onClick={logout} className="text-sm text-slate-500">
              退出
            </button>
          </div>
        </div>

        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-sky-100/80 bg-white/80 px-4 py-6 backdrop-blur md:flex">
          <div className="px-2">
            <Link href="/dashboard">
              <Logo size="sm" />
            </Link>
          </div>
          <nav className="mt-7 flex flex-col gap-1">
            {navItems.map((item) => {
              const active =
                item.href === "/dashboard"
                  ? pathname === "/dashboard"
                  : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm transition-colors ${
                    active
                      ? "bg-sky-50 font-medium text-sky-800"
                      : "text-slate-600 hover:bg-sky-50/70 hover:text-slate-900"
                  }`}
                >
                  {item.icon}
                  {item.label}
                </Link>
              );
            })}
            <Link
              href="/notifications"
              className={`flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm transition-colors ${
                pathname.startsWith("/notifications")
                  ? "bg-sky-50 font-medium text-sky-800"
                  : "text-slate-600 hover:bg-sky-50/70 hover:text-slate-900"
              }`}
            >
              <IconBell className="h-4.5 w-4.5" />
              通知
              {unread > 0 && (
                <span className="ml-auto rounded-full bg-sky-600 px-1.5 py-0.5 text-[10px] text-white">
                  {unread}
                </span>
              )}
            </Link>
            <Link
              href="/help"
              className={`flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm transition-colors ${
                pathname.startsWith("/help")
                  ? "bg-sky-50 font-medium text-sky-800"
                  : "text-slate-600 hover:bg-sky-50/70 hover:text-slate-900"
              }`}
            >
              <IconHelp className="h-4.5 w-4.5" />
              帮助
            </Link>
          </nav>
          <div className="mt-auto flex flex-col gap-1 border-t border-sky-100/80 pt-4">
            <div className="flex items-center gap-2.5 px-3 py-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-sky-100 text-sm font-semibold text-sky-800">
                {(username ?? "?")[0]?.toUpperCase()}
              </div>
              <span className="min-w-0 truncate text-sm text-slate-600">{username ?? "…"}</span>
            </div>
            {isAdmin ? (
              <Link
                href="/admin"
                className="px-3 py-1.5 text-left text-sm text-slate-500 transition-colors hover:text-slate-900"
              >
                进入运维后台 →
              </Link>
            ) : null}
            <button
              type="button"
              onClick={logout}
              className="px-3 py-1.5 text-left text-sm text-slate-500 transition-colors hover:text-slate-900"
            >
              退出登录
            </button>
          </div>
        </aside>

        <nav className="sticky bottom-0 z-20 flex border-t border-sky-100/80 bg-white/90 backdrop-blur md:hidden">
          {navItems.slice(0, 5).map((item) => {
            const active =
              item.href === "/dashboard" ? pathname === "/dashboard" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[11px] ${
                  active ? "text-sky-700" : "text-slate-500"
                }`}
              >
                {item.icon}
                {item.label}
              </Link>
            );
          })}
        </nav>

        <main className="flex min-h-0 flex-1 flex-col">{children}</main>
        <OnboardingModal />
      </div>
    </ToastProvider>
  );
}
