"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, Card, IconReport } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

type UsageSession = {
  session_id: number;
  provider: string;
  model: string;
  call_count: number;
  input_tokens: number;
  output_tokens: number;
  cost_yuan: number;
  created_at: string;
  target_role?: string;
  target_company?: string;
  status?: string;
};

type UsageData = {
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_yuan: number;
  session_count: number;
  recent: UsageSession[];
};

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtCost(v: number): string {
  if (v < 0.01) return `${(v * 100).toFixed(2)} 分`;
  return `¥${v.toFixed(4)}`;
}

function fmtTokens(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export default function UsagePage() {
  const [data, setData] = useState<UsageData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<UsageData>("/api/settings/usage")
      .then(setData)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          window.location.assign("/login");
        } else {
          setError(e instanceof Error ? e.message : "加载失败");
        }
      });
  }, []);

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <div className="text-sm text-red-600 dark:text-red-400">加载失败：{error}</div>
        <button
          onClick={() => window.location.reload()}
          className="rounded-lg border border-zinc-300 px-5 py-2 text-sm text-zinc-600 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          重试
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex flex-1 items-center justify-center text-zinc-500">加载中…</div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-5 px-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          用量查询
        </h1>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card className="flex flex-col items-center p-4 text-center">
          <div className="text-xs text-zinc-500 dark:text-zinc-400">累计花费</div>
          <div className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            {fmtCost(data.total_cost_yuan)}
          </div>
        </Card>
        <Card className="flex flex-col items-center p-4 text-center">
          <div className="text-xs text-zinc-500 dark:text-zinc-400">输入 Token</div>
          <div className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            {fmtTokens(data.total_input_tokens)}
          </div>
        </Card>
        <Card className="flex flex-col items-center p-4 text-center">
          <div className="text-xs text-zinc-500 dark:text-zinc-400">输出 Token</div>
          <div className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            {fmtTokens(data.total_output_tokens)}
          </div>
        </Card>
        <Card className="flex flex-col items-center p-4 text-center">
          <div className="text-xs text-zinc-500 dark:text-zinc-400">面试场次</div>
          <div className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            {data.session_count}
          </div>
        </Card>
      </div>

      <Card className="p-5">
        <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
          <IconReport className="h-4 w-4 text-teal-600 dark:text-teal-400" />
          最近面试
        </h2>
        {data.recent.length === 0 ? (
          <div className="py-8 text-center text-sm text-zinc-400 dark:text-zinc-500">暂无面试用量</div>
        ) : (
          <div className="flex flex-col divide-y divide-zinc-100 dark:divide-zinc-800">
            {data.recent.map((r) => (
              <div key={r.session_id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                <div className="flex min-w-0 items-center gap-2.5">
                  <Link
                    href={`/report/${r.session_id}`}
                    className="shrink-0 font-medium text-teal-600 hover:underline dark:text-teal-400"
                  >
                    面试 #{r.session_id}
                  </Link>
                  {r.provider ? <Badge tone="teal">{r.provider}</Badge> : null}
                  <span className="min-w-0 truncate text-zinc-600 dark:text-zinc-300">
                    {[r.target_company, r.target_role, r.model].filter(Boolean).join(" · ")}
                  </span>
                </div>
                <div className="flex shrink-0 items-center gap-3 text-xs text-zinc-400 dark:text-zinc-500">
                  <span>{r.call_count} 次</span>
                  <span>
                    {fmtTokens(r.input_tokens)} / {fmtTokens(r.output_tokens)}
                  </span>
                  <span className="w-16 text-right font-medium text-zinc-600 dark:text-zinc-300">
                    {fmtCost(r.cost_yuan)}
                  </span>
                  <span>{fmtTime(r.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
