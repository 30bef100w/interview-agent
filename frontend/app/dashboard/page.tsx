"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  Badge,
  ButtonLink,
  Card,
  IconArrowRight,
  IconChart,
  IconChat,
  IconCode,
  IconHistory,
  IconMic,
  IconReport,
  IconTarget,
  IconUpload,
  btnCls,
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
  const [feishuOn, setFeishuOn] = useState(false);
  const [feishuBound, setFeishuBound] = useState(false);
  const [feishuName, setFeishuName] = useState("");
  const [feishuBusy, setFeishuBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [noticeError, setNoticeError] = useState("");

  useEffect(() => {
    api<{ username: string; feishu_bound?: boolean; feishu_name?: string }>("/api/auth/me")
      .then((me) => {
        setUsername(me.username);
        setFeishuBound(Boolean(me.feishu_bound));
        setFeishuName((me.feishu_name || "").trim());
      })
      .catch(() => {});
    api<{ enabled: boolean }>("/api/auth/feishu/config")
      .then((d) => setFeishuOn(Boolean(d.enabled)))
      .catch(() => setFeishuOn(false));
    api<{ items: HistoryItem[] }>("/api/interview/history?page_size=50")
      .then((res) => setHistory(res.items ?? []))
      .catch(() => setLoadFailed(true));
    const q = new URLSearchParams(window.location.search);
    if (q.get("feishu") === "1") {
      setNotice("飞书已绑定。请在手机飞书里私聊深问机器人发「开始」，不要在群里发。");
    }
    const err = (q.get("feishu_error") || "").trim();
    if (err) setNoticeError(err);
    if (q.get("feishu") === "1" || err) {
      window.history.replaceState({}, "", "/dashboard");
    }
  }, []);

  async function bindFeishu() {
    setNotice("");
    setNoticeError("");
    setFeishuBusy(true);
    try {
      const res = await api<{ authorize_url: string }>("/api/auth/feishu/start?mode=bind");
      window.location.href = res.authorize_url;
    } catch (e) {
      setNoticeError(e instanceof Error ? e.message : "无法开始飞书绑定");
      setFeishuBusy(false);
    }
  }

  const finished = history.filter((h) => h.status === "finished");
  const active = history.filter((h) => h.status === "active" || h.status === "creating");
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

      {notice ? (
        <div className="animate-fade-in rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-400">
          {notice}
        </div>
      ) : null}
      {noticeError ? (
        <div className="animate-fade-in rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-400">
          {noticeError}
        </div>
      ) : null}

      {feishuOn ? (
        <Card
          id="feishu-bind"
          className="animate-fade-up flex scroll-mt-8 flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky-50 text-sky-600 dark:bg-sky-950/60 dark:text-sky-400">
              <IconChat className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
                {feishuBound ? "飞书面试已绑定" : "绑定飞书面试"}
              </div>
              <p className="mt-1 text-xs leading-5 text-zinc-500 dark:text-zinc-400">
                {feishuBound
                  ? `当前已绑定${feishuName ? `（${feishuName}）` : ""}。在手机飞书里私聊深问机器人即可，记录会同步到这个账号。`
                  : "绑定后可在手机飞书里私聊深问机器人面试，记录会同步到这个账号。"}
              </p>
            </div>
          </div>
          {feishuBound ? (
            <Link href="/settings#feishu" className={btnCls("secondary", "sm", "shrink-0")}>
              管理绑定
            </Link>
          ) : (
            <button
              type="button"
              disabled={feishuBusy}
              onClick={() => void bindFeishu()}
              className={btnCls("primary", "sm", "shrink-0")}
            >
              {feishuBusy ? "跳转中…" : "绑定飞书"}
            </button>
          )}
        </Card>
      ) : null}

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
                      ) : item.status === "abandoned" ? (
                        <Badge tone="amber">已退出</Badge>
                      ) : item.status === "failed" ? (
                        <Badge tone="red">规划失败</Badge>
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
                ) : item.status === "abandoned" || item.status === "failed" ? (
                  <Link
                    href="/interview/new"
                    className="shrink-0 text-xs font-medium text-zinc-500 hover:text-zinc-700 dark:text-zinc-400"
                  >
                    再开一场 →
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

