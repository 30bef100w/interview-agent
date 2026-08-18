"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

type Stats = {
  total_users: number;
  disabled_users: number;
  dau: number;
  mau: number;
  total_interviews: number;
  interviews_today: number;
  interviews_month: number;
  platform_cost_yuan: number;
  quota_granted_total: number;
  error_log_count: number;
};

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 p-4">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight text-zinc-50">{value}</div>
      {hint ? <div className="mt-1 text-[11px] text-zinc-500">{hint}</div> : null}
    </div>
  );
}

export default function AdminOverviewPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Stats>("/api/admin/stats")
      .then(setStats)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-zinc-50">运维概览</h1>
          <p className="mt-1 text-sm text-zinc-500">用户活跃、面试量与平台 Key 成本</p>
        </div>
        <div className="flex gap-2 text-sm">
          <Link
            href="/admin/users"
            className="rounded-lg border border-zinc-700 px-3 py-1.5 text-zinc-300 hover:border-zinc-500 hover:text-white"
          >
            用户管理
          </Link>
          <Link
            href="/admin/logs"
            className="rounded-lg border border-zinc-700 px-3 py-1.5 text-zinc-300 hover:border-zinc-500 hover:text-white"
          >
            系统日志
          </Link>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-red-900/60 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {!stats ? (
          <div className="col-span-full py-16 text-center text-zinc-500">加载中…</div>
        ) : (
          <>
            <Stat
              label="注册用户"
              value={stats.total_users}
              hint={`禁用 ${stats.disabled_users}`}
            />
            <Stat label="日活 DAU" value={stats.dau} hint="今日有活动" />
            <Stat label="月活 MAU" value={stats.mau} hint="近 30 天" />
            <Stat label="面试总场次" value={stats.total_interviews} />
            <Stat
              label="今日 / 本月面试"
              value={`${stats.interviews_today} / ${stats.interviews_month}`}
            />
            <Stat
              label="平台 Key 花费"
              value={`¥${stats.platform_cost_yuan.toFixed(4)}`}
              hint={`累计发放 ${stats.quota_granted_total} 次 · 错误 ${stats.error_log_count}`}
            />
          </>
        )}
      </div>
    </div>
  );
}
