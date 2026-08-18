"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { ToastProvider } from "@/components/Toast";
import { api, clearToken, getToken } from "@/lib/api";

const NAV = [
  { href: "/admin", label: "概览", exact: true },
  { href: "/admin/users", label: "用户管理" },
  { href: "/admin/logs", label: "系统日志" },
];

export default function AdminLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api<{ username: string; is_admin?: boolean }>("/api/auth/me")
      .then((me) => {
        if (!me.is_admin) {
          router.replace("/dashboard");
          return;
        }
        setUsername(me.username);
        setReady(true);
      })
      .catch(() => {
        clearToken();
        router.replace("/login");
      });
  }, [router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-950 text-sm text-zinc-400">
        校验管理员权限…
      </div>
    );
  }

  return (
    <ToastProvider>
      <div className="flex min-h-screen bg-zinc-950 text-zinc-100">
        <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-zinc-800 bg-zinc-900/80 px-3 py-5">
          <div className="px-2">
            <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-zinc-500">
              Ops Console
            </div>
            <div className="mt-1 text-sm font-semibold text-zinc-100">face-agent 运维</div>
          </div>
          <nav className="mt-6 flex flex-col gap-0.5">
            {NAV.map((item) => {
              const active = item.exact
                ? pathname === item.href
                : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-lg px-3 py-2 text-sm transition-colors ${
                    active
                      ? "bg-zinc-800 font-medium text-white"
                      : "text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-100"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="mt-auto space-y-1 border-t border-zinc-800 px-2 pt-4">
            <div className="truncate text-xs text-zinc-500">{username}</div>
            <Link
              href="/dashboard"
              className="block text-sm text-zinc-400 transition-colors hover:text-zinc-100"
            >
              ← 返回用户端
            </Link>
          </div>
        </aside>
        <main className="min-w-0 flex-1 overflow-auto">{children}</main>
      </div>
    </ToastProvider>
  );
}
