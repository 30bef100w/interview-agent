"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { TracePayload, TraceTimeline } from "@/components/admin/TraceTimeline";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";

export default function AdminSessionTracePage() {
  const params = useParams();
  const sessionId = params.sessionId as string;
  const [trace, setTrace] = useState<TracePayload | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    api<TracePayload>(`/api/observability/sessions/${sessionId}/trace`)
      .then(setTrace)
      .catch((e) => setError(e instanceof Error ? e.message : "Trace 加载失败"));
  }, [sessionId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-zinc-100">会话 Trace #{sessionId}</h1>
          <p className="mt-1 text-sm text-zinc-400">
            规划 / 引擎节点 / 门禁事件合并时间线（仅运维可见）
          </p>
        </div>
        <Link
          href="/admin/observability"
          className="text-sm text-sky-400 hover:text-sky-300"
        >
          ← 返回可观测性
        </Link>
      </div>

      {error ? <ErrorBanner message={error} onRetry={load} /> : null}

      {!trace ? (
        <p className="text-sm text-zinc-500">加载中…</p>
      ) : (
        <TraceTimeline
          trace={trace}
          showRaw={showRaw}
          onToggleRaw={() => setShowRaw((v) => !v)}
        />
      )}
    </div>
  );
}
