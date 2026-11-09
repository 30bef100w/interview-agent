"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { PageHeading, formatTime as fmtTime } from "@/components/admin/AdminUI";
import s from "../admin.module.css";

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
    <div className={s.page}>
      <PageHeading title="系统日志" description={`追踪错误、告警与管理员操作 · 共 ${total} 条记录`} />

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
                ? "bg-violet-600 font-medium text-white"
                : "bg-white text-slate-600 hover:bg-slate-100 hover:text-slate-800"
            }`}
          >
            {lv || "全部"}
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-3 rounded-lg border border-red-200/60 bg-red-50/50 px-3 py-2 text-sm text-red-600">
          {error}
        </div>
      )}

      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b border-slate-200 bg-white text-xs text-slate-500">
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
                className="cursor-pointer border-b border-slate-200/80 last:border-0 hover:bg-slate-50"
                onClick={() => setSelected(row)}
              >
                <td className="whitespace-nowrap px-3 py-2.5 text-xs text-slate-500">
                  {fmtTime(row.created_at)}
                </td>
                <td className="px-3 py-2.5">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                      row.level === "error"
                        ? "bg-red-50 text-red-600"
                        : row.level === "warning"
                          ? "bg-amber-50 text-amber-700"
                          : "bg-slate-100 text-slate-700"
                    }`}
                  >
                    {row.level}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-xs text-slate-600">{row.source || "—"}</td>
                <td className="px-3 py-2.5 font-mono text-xs text-slate-600">{row.path || "—"}</td>
                <td className="max-w-md truncate px-3 py-2.5 text-slate-800">{row.message}</td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-10 text-center text-slate-500">
                  暂无日志
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selected && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4"
          onClick={() => setSelected(null)}
        >
          <div
            className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-xl border border-slate-200 bg-white p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-slate-900">{selected.message}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {fmtTime(selected.created_at)} · {selected.path} · {selected.source}
                  {selected.user_id != null ? ` · user#${selected.user_id}` : ""}
                </div>
              </div>
              <button
                type="button"
                className="text-sm text-slate-500 hover:text-slate-800"
                onClick={() => setSelected(null)}
              >
                关闭
              </button>
            </div>
            <pre className="mt-4 overflow-x-auto rounded-lg bg-slate-100 p-4 text-xs leading-relaxed text-slate-700">
              {selected.detail || "（无详情）"}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
