"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  Badge,
  ButtonLink,
  Card,
  IconArrowRight,
  IconChart,
  IconCode,
  IconHistory,
  IconMic,
  IconReport,
  IconTarget,
  IconUpload,
} from "@/components/ui";
import { api } from "@/lib/api";

type HistoryItem = {
  session_id: number;
  mode: string;
  type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  rounds_used: number;
  question_count: number;
  has_report: boolean;
};

function modeLabel(item: HistoryItem): string {
  if (item.mode === "full") return "全流程混合面";
  const typeLabel: Record<string, string> = {
    project: "项目深挖",
    ba_gu: "八股专场",
    hr: "HR 行为面",
  };
  return `专项 · ${typeLabel[item.type] ?? item.type}`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const ACTIONS = [
  {
    href: "/interview/new",
    icon: <IconMic className="h-5 w-5" />,
    title: "开始模拟面试",
    desc: "全流程混合面或专项专场，AI 面试官实时追问",
    primary: true,
  },
  {
    href: "/resume/upload",
    icon: <IconUpload className="h-5 w-5" />,
    title: "上传 / 管理简历",
    desc: "AI 解析画像，作为面试官的提问依据",
    primary: false,
  },
  {
    href: "/history",
    icon: <IconHistory className="h-5 w-5" />,
    title: "面试记录",
    desc: "回看历史面试，对照报告复盘表现",
    primary: false,
  },
  {
    href: "/growth",
    icon: <IconChart className="h-5 w-5" />,
    title: "成长档案",
    desc: "跨场次复盘进步与欠缺，可选针对性再练",
    primary: false,
  },
];

export default function DashboardPage() {
  const [username, setUsername] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    api<{ username: string }>("/api/auth/me")
      .then((me) => setUsername(me.username))
      .catch(() => {});
    api<{ items: HistoryItem[] }>("/api/interview/history?page_size=50")
      .then((res) => setHistory(res.items ?? []))
      .catch(() => setLoadFailed(true));
  }, []);

  const finished = history.filter((h) => h.status === "finished");
  const active = history.filter((h) => h.status !== "finished");
  const recent = history.slice(0, 5);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-6 py-8">
      <section className="animate-fade-up">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          {username ? `你好，${username}` : "你好"}
        </h1>
        <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
          多练一场，面试多一分把握。今天想练点什么？
        </p>
      </section>

      <section className="grid grid-cols-3 gap-3">
        {[
          { label: "累计面试", value: history.length, icon: <IconHistory className="h-4 w-4" /> },
          { label: "已出报告", value: finished.length, icon: <IconReport className="h-4 w-4" /> },
          { label: "进行中", value: active.length, icon: <IconCode className="h-4 w-4" /> },
        ].map((s, i) => (
          <Card
            key={s.label}
            className="animate-fade-up flex items-center gap-3 p-4"
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-600 dark:bg-sky-950/60 dark:text-sky-400">
              {s.icon}
            </div>
            <div className="min-w-0">
              <div className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">{s.value}</div>
              <div className="truncate text-xs text-zinc-500 dark:text-zinc-400">{s.label}</div>
            </div>
          </Card>
        ))}
      </section>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {ACTIONS.map((a, i) => (
          <Link
            key={a.href}
            href={a.href}
            className={`group animate-fade-up rounded-2xl border p-5 transition-all duration-200 hover:-translate-y-0.5 ${
              a.primary
                ? "border-sky-200 bg-gradient-to-br from-sky-600 to-emerald-600 text-white shadow-lg shadow-sky-600/25 hover:shadow-xl hover:shadow-sky-600/30 dark:border-sky-800"
                : "border-zinc-200/80 bg-white shadow-sm shadow-zinc-900/[0.03] hover:border-sky-200 hover:shadow-lg hover:shadow-sky-600/[0.06] dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-sky-800/60"
            }`}
            style={{ animationDelay: `${0.05 + i * 0.06}s` }}
          >
            <div
              className={`mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl ${
                a.primary
                  ? "bg-white/15 text-white"
                  : "bg-sky-50 text-sky-600 transition-colors group-hover:bg-sky-100 dark:bg-sky-950/60 dark:text-sky-400"
              }`}
            >
              {a.icon}
            </div>
            <div className={`text-sm font-semibold ${a.primary ? "text-white" : "text-zinc-900 dark:text-zinc-50"}`}>
              {a.title}
            </div>
            <div className={`mt-1 text-xs leading-5 ${a.primary ? "text-sky-100" : "text-zinc-500 dark:text-zinc-400"}`}>
              {a.desc}
            </div>
          </Link>
        ))}
      </section>

      <section className="animate-fade-up" style={{ animationDelay: "0.2s" }}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">最近面试</h2>
          <Link
            href="/history"
            className="inline-flex items-center gap-1 text-xs text-zinc-500 transition-colors hover:text-sky-600 dark:text-zinc-400 dark:hover:text-sky-400"
          >
            全部记录 <IconArrowRight className="h-3 w-3" />
          </Link>
        </div>

        {loadFailed ? (
          <Card className="p-4 text-sm text-zinc-500 dark:text-zinc-400">历史记录加载失败</Card>
        ) : recent.length === 0 ? (
          <Card className="flex flex-col items-center gap-3 p-8 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-sky-50 text-sky-500 dark:bg-sky-950/60 dark:text-sky-400">
              <IconTarget className="h-6 w-6" />
            </div>
            <div className="text-sm text-zinc-500 dark:text-zinc-400">还没有面试记录，来一场试试吧</div>
            <ButtonLink href="/interview/new" className="">
              开始第一场面试
            </ButtonLink>
          </Card>
        ) : (
          <Card className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {recent.map((item) => (
              <div key={item.session_id} className="flex items-center justify-between px-5 py-3.5">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                    <IconMic className="h-3.5 w-3.5" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-50">
                        {modeLabel(item)}
                      </span>
                      {item.status === "finished" ? (
                        <Badge tone="zinc">已结束</Badge>
                      ) : (
                        <Badge tone="emerald">进行中</Badge>
                      )}
                    </div>
                    <div className="mt-0.5 text-xs text-zinc-400 dark:text-zinc-500">
                      {fmtTime(item.started_at)} · 已回答 {item.rounds_used} 轮
                    </div>
                  </div>
                </div>
                {item.has_report ? (
                  <Link
                    href={`/report/${item.session_id}`}
                    className="shrink-0 text-xs font-medium text-sky-600 hover:text-sky-500 dark:text-sky-400"
                  >
                    查看报告 →
                  </Link>
                ) : (
                  <Link
                    href={`/interview/${item.session_id}`}
                    className="shrink-0 text-xs font-medium text-sky-600 hover:text-sky-500 dark:text-sky-400"
                  >
                    继续面试 →
                  </Link>
                )}
              </div>
            ))}
          </Card>
        )}
      </section>
    </div>
  );
}

