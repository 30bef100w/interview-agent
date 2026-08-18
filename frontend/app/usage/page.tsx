"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, Card, IconReport } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

type UsageItem = {
  session_id: number | null;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_yuan: number;
  created_at: string;
};

type UsageData = {
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_yuan: number;
  session_count: number;
  recent: UsageItem[];
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
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          你的每次 AI 调用都实时统计，费用按模型单价换算
        </p>
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
            {(data.total_input_tokens / 10000).toFixed(1)}万
          </div>
        </Card>
        <Card className="flex flex-col items-center p-4 text-center">
          <div className="text-xs text-zinc-500 dark:text-zinc-400">输出 Token</div>
          <div className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            {(data.total_output_tokens / 10000).toFixed(1)}万
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
          最近调用
        </h2>
        {data.recent.length === 0 ? (
          <div className="py-8 text-center text-sm text-zinc-400 dark:text-zinc-500">
            还没有 AI 调用记录，开始一场面试就有了
          </div>
        ) : (
          <div className="flex flex-col divide-y divide-zinc-100 dark:divide-zinc-800">
            {data.recent.map((r, i) => (
              <div key={i} className="flex items-center justify-between py-2.5 text-sm">
                <div className="flex min-w-0 items-center gap-2.5">
                  <Badge tone="teal">{r.provider}</Badge>
                  <span className="min-w-0 truncate text-zinc-600 dark:text-zinc-300">{r.model}</span>
                </div>
                <div className="flex shrink-0 items-center gap-3 text-xs text-zinc-400 dark:text-zinc-500">
                  <span>
                    {r.session_id ? (
                      <Link
                        href={`/report/${r.session_id}`}
                        className="text-teal-600 hover:underline dark:text-teal-400"
                      >
                        面试 #{r.session_id}
                      </Link>
                    ) : (
                      "其他"
                    )}
                  </span>
                  <span>
                    {(r.input_tokens / 1000).toFixed(1)}k / {(r.output_tokens / 1000).toFixed(1)}k
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
