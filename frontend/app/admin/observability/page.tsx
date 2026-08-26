"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorBanner, Card } from "@/components/ui";
import { api } from "@/lib/api";

type Metrics = {
  nodes: Record<string, { count: number; errors: number; avg_ms: number; p95_ms: number }>;
  llm: { calls: number; errors: number };
};

export default function AdminObservabilityPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [trace, setTrace] = useState<Record<string, unknown> | null>(null);
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
    api<Record<string, unknown>>(`/api/observability/sessions/${id}/trace`)
      .then(setTrace)
      .catch((e) => setError(e instanceof Error ? e.message : "Trace 加载失败"));
  }

  const nodes = Object.entries(metrics?.nodes || {}).sort((a, b) => b[1].count - a[1].count);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-100">可观测性</h1>
        <p className="mt-1 text-sm text-zinc-400">
          引擎节点耗时与错误率（内存聚合，参考 Gua GraphTrace）；会话级 trace 合并 create_trace / engine_trace / session_guard。
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
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            placeholder="session_id"
            className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-sky-600"
          />
          <button
            type="button"
            onClick={loadTrace}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm text-white hover:bg-sky-500"
          >
            查询
          </button>
        </div>
        {trace ? (
          <pre className="mt-4 max-h-96 overflow-auto rounded-lg bg-zinc-950 p-3 text-xs text-zinc-300">
            {JSON.stringify(trace, null, 2)}
          </pre>
        ) : null}
      </Card>
    </div>
  );
}
