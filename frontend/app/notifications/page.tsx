"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useToast } from "@/components/Toast";
import { Badge, EmptyState, btnCls } from "@/components/ui";
import {
  clearNotifications,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type AppNotification,
} from "@/lib/notifications";

function fmt(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const KIND: Record<AppNotification["kind"], string> = {
  resume: "简历",
  interview: "面试",
  report: "报告",
  system: "系统",
};

export default function NotificationsPage() {
  const toast = useToast();
  const [items, setItems] = useState<AppNotification[]>([]);

  function refresh() {
    setItems(listNotifications());
  }

  useEffect(() => {
    refresh();
    const onChange = () => refresh();
    window.addEventListener("fa-notifications", onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener("fa-notifications", onChange);
      window.removeEventListener("storage", onChange);
    };
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">通知中心</h1>
          <p className="mt-1 text-sm text-zinc-500">
            只汇总后台异步完成的事项（例如你离开页面后才完成的任务）。当面操作的结果不会推到这里。
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className={btnCls("secondary", "sm")}
            onClick={() => {
              markAllNotificationsRead();
              refresh();
              toast.ok("已全部标为已读");
            }}
          >
            全部已读
          </button>
          <button
            type="button"
            className={btnCls("ghost", "sm")}
            onClick={() => {
              clearNotifications();
              refresh();
              toast.info("已清空通知");
            }}
          >
            清空
          </button>
        </div>
      </div>

      {items.length === 0 ? (
        <EmptyState
          title="暂无异步通知"
          desc="你正在页面上等待的操作（上传、分析、开面试）完成后会直接展示，不会进通知中心"
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((n) => (
            <li key={n.id}>
              <Link
                href={n.href || "#"}
                onClick={() => markNotificationRead(n.id)}
                className={`block rounded-2xl border px-4 py-3 transition hover:border-sky-200 hover:bg-sky-50/40 ${
                  n.read
                    ? "border-zinc-100 bg-white"
                    : "border-sky-100 bg-sky-50/70"
                }`}
              >
                <div className="flex items-center gap-2">
                  <Badge tone={n.read ? "zinc" : "sky"}>{KIND[n.kind]}</Badge>
                  <span className="text-sm font-semibold text-zinc-900">{n.title}</span>
                  <span className="ml-auto text-[11px] text-zinc-400">{fmt(n.createdAt)}</span>
                </div>
                <p className="mt-1 text-sm text-zinc-500">{n.body}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
