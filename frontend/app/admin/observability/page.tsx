"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { TracePayload, TraceTimeline } from "@/components/admin/TraceTimeline";
import { ErrorBanner, Card } from "@/components/ui";
import { api } from "@/lib/api";

type Metrics = {
  nodes: Record<string, { count: number; errors: number; avg_ms: number; p95_ms: number }>;
  llm: { calls: number; errors: number };
};

export default function AdminObservabilityPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [trace, setTrace] = useState<TracePayload | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [error, setError] = useState("");

  const loadMetrics = useCallback(() => {
    setError("");
    api<Metrics>("/api/observability/metrics")
      .then(setMetrics)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, []);

  useEffect(() => {
    loadMetrics();
  }, [loadMetrics]);

  function loadTrace() {
    const id = sessionId.trim();
    if (!id) return;
    setError("");
    setShowRaw(false);
    api<TracePayload>(`/api/observability/sessions/${id}/trace`)
      .then(setTrace)
      .catch((e) => setError(e instanceof Error ? e.message : "Trace 加载失败"));
  }

  const nodes = Object.entries(metrics?.nodes || {}).sort((a, b) => b[1].count - a[1].count);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-100">可观测性</h1>
        <p className="mt-1 text-sm text-zinc-400">
          引擎节点耗时与错误率；会话级 trace 合并 create_trace / engine_trace / session_guard（仅运维端）
        </p>
      </div>

      {error ? <ErrorBanner message={error} onRetry={loadMetrics} /> : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="border-zinc-800 bg-zinc-900/60 p-4 text-zinc-100">
          <div className="text-xs text-zinc-500">LLM 调用</div>
          <div className="mt-1 text-2xl font-semibold">{metrics?.llm.calls ?? "-"}</div>
          <div className="mt-1 text-xs text-zinc-400">错误 {metrics?.llm.errors ?? 0}</div>
        </Card>
        <Card className="border-zinc-800 bg-zinc-900/60 p-4 text-zinc-100">
          <div className="text-xs text-zinc-500">已追踪节点种类</div>
          <div className="mt-1 text-2xl font-semibold">{nodes.length}</div>
          <div className="mt-1 text-xs text-zinc-400">重启后清零（进程内指标）</div>
        </Card>
      </div>

      <Card className="overflow-hidden border-zinc-800 bg-zinc-900/60">
        <div className="border-b border-zinc-800 px-4 py-3 text-sm font-medium text-zinc-200">
          节点耗时 Top
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-zinc-300">
            <thead className="text-xs text-zinc-500">
              <tr>
                <th className="px-4 py-2">节点</th>
                <th className="px-4 py-2">次数</th>
                <th className="px-4 py-2">错误</th>
                <th className="px-4 py-2">avg ms</th>
                <th className="px-4 py-2">p95 ms</th>
              </tr>
            </thead>
            <tbody>
              {nodes.map(([name, row]) => (
                <tr key={name} className="border-t border-zinc-800/80">
                  <td className="px-4 py-2 font-mono text-xs">{name}</td>
                  <td className="px-4 py-2">{row.count}</td>
                  <td className="px-4 py-2">{row.errors}</td>
                  <td className="px-4 py-2">{row.avg_ms}</td>
                  <td className="px-4 py-2">{row.p95_ms}</td>
                </tr>
              ))}
              {nodes.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-zinc-500">
                    暂无节点数据，创建几场面试后刷新
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="border-zinc-800 bg-zinc-900/60 p-4">
        <div className="text-sm font-medium text-zinc-200">会话 Trace 查询</div>
        <p className="mt-1 text-xs text-zinc-500">
          输入面试 session_id，查看规划耗时、引擎节点与兜底门禁事件时间线
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && loadTrace()}
            placeholder="session_id，如 78"
            className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-sky-600"
          />
          <button
            type="button"
            onClick={loadTrace}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm text-white hover:bg-sky-500"
          >
            查询
          </button>
          {sessionId.trim() ? (
            <Link
              href={`/admin/observability/sessions/${sessionId.trim()}`}
              className="rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:border-zinc-500"
            >
              独立页面打开
            </Link>
          ) : null}
        </div>
        {trace ? (
          <div className="mt-4">
            <TraceTimeline
              trace={trace}
              showRaw={showRaw}
              onToggleRaw={() => setShowRaw((v) => !v)}
            />
          </div>
        ) : null}
      </Card>
    </div>
  );
}
