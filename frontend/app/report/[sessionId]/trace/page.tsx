"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ErrorBanner } from "@/components/ui";
import { ApiError, api, getToken } from "@/lib/api";

export default function SessionTracePage() {
  const params = useParams();
  const sessionId = params.sessionId as string;
  const router = useRouter();
  const [trace, setTrace] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    api<Record<string, unknown>>(`/api/observability/sessions/${sessionId}/trace`)
      .then(setTrace)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          router.replace("/login");
        } else {
          setError(e instanceof Error ? e.message : "加载失败");
        }
      });
  }, [sessionId, router]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    load();
  }, [load, router]);

  return (
    <div className="mx-auto max-w-4xl space-y-4 px-4 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">会话 Trace #{sessionId}</h1>
          <p className="mt-1 text-sm text-slate-500">
            create_trace / engine_trace / session_guard 合并视图（开发 & 管理员）
          </p>
        </div>
        <Link
          href={`/report/${sessionId}`}
          className="text-sm text-sky-700 hover:text-sky-600"
        >
          ← 返回报告
        </Link>
      </div>

      {error ? <ErrorBanner message={error} onRetry={load} /> : null}

      <pre className="max-h-[75vh] overflow-auto rounded-2xl border border-zinc-200 bg-zinc-950 p-4 text-xs leading-relaxed text-zinc-300">
        {trace ? JSON.stringify(trace, null, 2) : "加载中…"}
      </pre>
    </div>
  );
}
