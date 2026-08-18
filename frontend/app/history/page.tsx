"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  ButtonLink,
  Card,
  EmptyState,
  ErrorBanner,
  IconArrowRight,
  IconHistory,
  IconReport,
  btnCls,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";

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
  target_role?: string;
  target_company?: string;
};

type HistoryRes = {
  items: HistoryItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
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

export default function HistoryPage() {
  const [data, setData] = useState<HistoryRes | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [targetRole, setTargetRole] = useState("");
  const [targetCompany, setTargetCompany] = useState("");
  const [page, setPage] = useState(1);
  const [applied, setApplied] = useState({
    q: "",
    status: "",
    targetRole: "",
    targetCompany: "",
  });

  const load = useCallback(() => {
    setError("");
    const params = new URLSearchParams({
      page: String(page),
      page_size: "10",
    });
    if (applied.q.trim()) params.set("q", applied.q.trim());
    if (applied.status) params.set("status", applied.status);
    if (applied.targetRole.trim()) params.set("target_role", applied.targetRole.trim());
    if (applied.targetCompany.trim()) params.set("target_company", applied.targetCompany.trim());

    api<HistoryRes>(`/api/interview/history?${params}`)
      .then(setData)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          window.location.assign("/login");
        } else {
          setError(e instanceof Error ? e.message : "加载失败");
        }
      });
  }, [page, applied]);

  useEffect(() => {
    load();
  }, [load]);

  function applyFilters(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setApplied({ q, status, targetRole, targetCompany });
  }

  const items = data?.items ?? null;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-5 px-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          面试记录
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          回看每场面试，复盘进步。可按目标岗位 / 企业筛选
        </p>
      </div>

      <form
        onSubmit={applyFilters}
        className="grid gap-3 rounded-2xl border border-zinc-200/80 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 sm:grid-cols-2 lg:grid-cols-5"
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索关键词"
          className="h-10 rounded-xl border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20 dark:border-zinc-700 dark:bg-zinc-950"
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="h-10 rounded-xl border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-sky-400 dark:border-zinc-700 dark:bg-zinc-950"
        >
          <option value="">全部状态</option>
          <option value="finished">已结束</option>
          <option value="active">进行中</option>
          <option value="abandoned">已退出</option>
        </select>
        <input
          value={targetRole}
          onChange={(e) => setTargetRole(e.target.value)}
          placeholder="目标岗位，如 Java 后端"
          className="h-10 rounded-xl border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-sky-400 dark:border-zinc-700 dark:bg-zinc-950"
        />
        <input
          value={targetCompany}
          onChange={(e) => setTargetCompany(e.target.value)}
          placeholder="目标企业，如 腾讯"
          className="h-10 rounded-xl border border-zinc-200 bg-white px-3 text-sm outline-none focus:border-sky-400 dark:border-zinc-700 dark:bg-zinc-950"
        />
        <button type="submit" className={btnCls("primary", "md", "h-10")}>
          筛选
        </button>
      </form>

      {error && <ErrorBanner message={error} onRetry={load} />}

      {!error && items === null && (
        <div className="flex flex-1 items-center justify-center">
          <div className="flex items-center gap-2 text-sm text-zinc-400">
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-dot" />
            加载中
          </div>
        </div>
      )}

      {items !== null && items.length === 0 && (
        <EmptyState
          icon={<IconHistory className="h-10 w-10" />}
          title="没有匹配的面试记录"
          desc="换个筛选条件，或开始你的下一场模拟面试"
          action={<ButtonLink href="/interview/new">开始面试</ButtonLink>}
        />
      )}

      <div className="flex flex-col gap-3">
        {items?.map((item, i) => (
          <Card
            key={item.session_id}
            className="animate-fade-up flex items-center justify-between px-5 py-4"
            style={{ animationDelay: `${Math.min(i * 0.04, 0.3)}s` }}
          >
            <div className="flex min-w-0 items-center gap-3.5">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky-50 text-sky-600 dark:bg-sky-950/60 dark:text-sky-400">
                {item.has_report ? (
                  <IconReport className="h-4.5 w-4.5" />
                ) : (
                  <IconHistory className="h-4.5 w-4.5" />
                )}
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-50">
                    {modeLabel(item)}
                  </span>
                  {item.status === "finished" ? (
                    <Badge tone="zinc">已结束</Badge>
                  ) : item.status === "abandoned" ? (
                    <Badge tone="amber">已退出</Badge>
                  ) : (
                    <Badge tone="emerald">进行中</Badge>
                  )}
                  {item.target_role ? <Badge tone="sky">{item.target_role}</Badge> : null}
                  {item.target_company ? <Badge tone="zinc">{item.target_company}</Badge> : null}
                </div>
                <div className="mt-0.5 text-xs text-zinc-400 dark:text-zinc-500">
                  {fmtTime(item.started_at)} · 已回答 {item.rounds_used} 轮
                  {item.finished_at && ` · 结束于 ${fmtTime(item.finished_at)}`}
                </div>
              </div>
            </div>
            {item.has_report ? (
              <Link
                href={`/report/${item.session_id}`}
                className="inline-flex shrink-0 items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium text-sky-600 transition-colors hover:bg-sky-50 dark:text-sky-400"
              >
                查看报告 <IconArrowRight className="h-3 w-3" />
              </Link>
            ) : item.status === "abandoned" ? (
              <Link
                href="/interview/new"
                className="inline-flex shrink-0 items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium text-zinc-500 transition-colors hover:bg-zinc-50 dark:text-zinc-400"
              >
                再开一场 <IconArrowRight className="h-3 w-3" />
              </Link>
            ) : (
              <Link
                href={`/interview/${item.session_id}`}
                className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-sky-600 px-3.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-sky-500"
              >
                继续面试 <IconArrowRight className="h-3 w-3" />
              </Link>
            )}
          </Card>
        ))}
      </div>

      {data && data.total_pages > 1 && (
        <div className="flex items-center justify-center gap-3 pt-2">
          <button
            type="button"
            disabled={page <= 1}
            className={btnCls("secondary", "sm")}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </button>
          <span className="text-xs text-zinc-500">
            {data.page} / {data.total_pages} · 共 {data.total} 场
          </span>
          <button
            type="button"
            disabled={page >= data.total_pages}
            className={btnCls("secondary", "sm")}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}
