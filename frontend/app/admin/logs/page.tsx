"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

type SystemLogItem = {
  id: number;
  level: string;
  source: string;
  path: string;
  message: string;
  detail: string;
  user_id: number | null;
  created_at: string;
};

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function AdminLogsPage() {
  const [logs, setLogs] = useState<SystemLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [level, setLevel] = useState("");
  const [selected, setSelected] = useState<SystemLogItem | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async (lv = level) => {
    const qs = new URLSearchParams({ limit: "100" });
    if (lv) qs.set("level", lv);
    const res = await api<{ items: SystemLogItem[]; total: number }>(`/api/admin/logs?${qs}`);
    setLogs(res.items);
    setTotal(res.total);
  }, [level]);

  useEffect(() => {
    load().catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div>
        <h1 className="text-xl font-semibold text-zinc-50">系统日志</h1>
        <p className="mt-1 text-sm text-zinc-500">错误、告警与管理员操作审计（共 {total} 条）</p>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {["", "error", "warning", "info"].map((lv) => (
          <button
            key={lv || "all"}
            type="button"
            onClick={() => {
              setLevel(lv);
              load(lv).catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
            }}
            className={`rounded-lg px-3 py-1.5 text-xs ${
              level === lv
                ? "bg-zinc-100 font-medium text-zinc-900"
                : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            }`}
          >
            {lv || "全部"}
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-3 rounded-lg border border-red-900/60 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="mt-4 overflow-hidden rounded-xl border border-zinc-800">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b border-zinc-800 bg-zinc-900 text-xs text-zinc-500">
            <tr>
              <th className="px-3 py-2.5 font-medium">时间</th>
              <th className="px-3 py-2.5 font-medium">级别</th>
              <th className="px-3 py-2.5 font-medium">来源</th>
              <th className="px-3 py-2.5 font-medium">路径</th>
              <th className="px-3 py-2.5 font-medium">摘要</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((row) => (
              <tr
                key={row.id}
                className="cursor-pointer border-b border-zinc-800/80 last:border-0 hover:bg-zinc-900/80"
                onClick={() => setSelected(row)}
              >
                <td className="whitespace-nowrap px-3 py-2.5 text-xs text-zinc-500">
                  {fmtTime(row.created_at)}
                </td>
                <td className="px-3 py-2.5">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                      row.level === "error"
                        ? "bg-red-950 text-red-300"
                        : row.level === "warning"
                          ? "bg-amber-950 text-amber-300"
                          : "bg-zinc-800 text-zinc-300"
                    }`}
                  >
                    {row.level}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-xs text-zinc-400">{row.source || "—"}</td>
                <td className="px-3 py-2.5 font-mono text-xs text-zinc-400">{row.path || "—"}</td>
                <td className="max-w-md truncate px-3 py-2.5 text-zinc-200">{row.message}</td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-10 text-center text-zinc-500">
                  暂无日志
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selected && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => setSelected(null)}
        >
          <div
            className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-xl border border-zinc-700 bg-zinc-900 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-zinc-50">{selected.message}</div>
                <div className="mt-1 text-xs text-zinc-500">
                  {fmtTime(selected.created_at)} · {selected.path} · {selected.source}
                  {selected.user_id != null ? ` · user#${selected.user_id}` : ""}
                </div>
              </div>
              <button
                type="button"
                className="text-sm text-zinc-500 hover:text-zinc-200"
                onClick={() => setSelected(null)}
              >
                关闭
              </button>
            </div>
            <pre className="mt-4 overflow-x-auto rounded-lg bg-black p-4 text-xs leading-relaxed text-zinc-300">
              {selected.detail || "（无详情）"}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
