"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { PageHeading, formatTime as fmtTime } from "@/components/admin/AdminUI";
import s from "../admin.module.css";

type AdminUser = {
  id: number;
  username: string;
  is_admin: boolean;
  is_test: boolean;
  is_disabled: boolean;
  platform_quota: number;
  uses_platform_key: boolean;
  has_own_key: boolean;
  interview_count: number;
  platform_cost_yuan: number;
  last_active_at: string | null;
  created_at: string;
};

type UserDetail = AdminUser & {
  recent_sessions: {
    id: number;
    status: string;
    mode: string;
    type: string;
    started_at: string;
    finished_at: string | null;
  }[];
  quota_grants: {
    id: number;
    admin_id: number | null;
    delta: number;
    note: string;
    created_at: string;
  }[];
};

const inputCls =
  "h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none focus:border-violet-400";

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [okMsg, setOkMsg] = useState("");
  const [selected, setSelected] = useState<UserDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [quotaDelta, setQuotaDelta] = useState("100");
  const [quotaSet, setQuotaSet] = useState("");
  const [quotaNote, setQuotaNote] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const loadUsers = useCallback(async (keyword = q, st = status) => {
    const qs = new URLSearchParams({ limit: "100" });
    if (keyword.trim()) qs.set("q", keyword.trim());
    if (st) qs.set("status", st);
    const res = await api<{ items: AdminUser[]; total: number }>(`/api/admin/users?${qs}`);
    setUsers(res.items);
    setTotal(res.total);
  }, [q, status]);

  useEffect(() => {
    loadUsers().catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, [loadUsers]);

  async function openDetail(id: number) {
    setError("");
    setOkMsg("");
    setNewPassword("");
    setQuotaNote("");
    try {
      const detail = await api<UserDetail>(`/api/admin/users/${id}`);
      setSelected(detail);
      setQuotaSet(String(detail.platform_quota));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载用户失败");
    }
  }

  async function refreshSelected(id: number) {
    const detail = await api<UserDetail>(`/api/admin/users/${id}`);
    setSelected(detail);
    setQuotaSet(String(detail.platform_quota));
    await loadUsers();
  }

  async function run(action: () => Promise<void>, ok: string) {
    setBusy(true);
    setError("");
    setOkMsg("");
    try {
      await action();
      setOkMsg(ok);
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    }
    setBusy(false);
  }

  return (
    <div className={`${s.page} flex flex-col gap-5 xl:flex-row xl:items-start`}>
      <div className="min-w-0 flex-1">
        <PageHeading title="用户管理" description={`管理用户账号、面试额度与访问权限 · 共 ${total} 位用户`} />

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && loadUsers()}
            placeholder="搜索用户名或 ID"
            aria-label="搜索用户名或 ID"
            className={`${inputCls} w-64 max-w-full`}
          />
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            aria-label="用户状态"
            className={`${inputCls} w-36`}
          >
            <option value="">全部状态</option>
            <option value="active">正常</option>
            <option value="disabled">已禁用</option>
            <option value="admin">管理员</option>
          </select>
          <button
            type="button"
            onClick={() => loadUsers()}
            className="h-9 rounded-lg bg-violet-600 px-3 text-sm font-medium text-white hover:bg-violet-500"
          >
            搜索
          </button>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-red-200/60 bg-red-50/50 px-3 py-2 text-sm text-red-600">
            {error}
          </div>
        )}
        {okMsg && (
          <div className="mt-3 rounded-lg border border-emerald-200/50 bg-emerald-50/40 px-3 py-2 text-sm text-emerald-700">
            {okMsg}
          </div>
        )}

        <div className="mt-5 overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full min-w-[680px] text-left text-sm">
            <thead className="border-b border-slate-200 bg-white text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2.5 font-medium">用户</th>
                <th className="px-3 py-2.5 font-medium">状态</th>
                <th className="px-3 py-2.5 font-medium">额度</th>
                <th className="px-3 py-2.5 font-medium">面试</th>
                <th className="px-3 py-2.5 font-medium">最近活跃</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr
                  key={u.id}
                  onClick={() => openDetail(u.id)}
                  className={`cursor-pointer border-b border-slate-200/80 last:border-0 hover:bg-slate-50 ${
                    selected?.id === u.id ? "bg-white" : ""
                  }`}
                >
                  <td className="px-3 py-2.5">
                    <div className="font-medium text-slate-900">{u.username}</div>
                    <div className="text-[11px] text-slate-500">#{u.id}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {u.is_disabled ? (
                        <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] text-red-600">
                          禁用
                        </span>
                      ) : (
                        <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">
                          正常
                        </span>
                      )}
                      {u.is_admin ? (
                        <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
                          管理员
                        </span>
                      ) : null}
                      {u.is_test && <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-600">测试账号</span>}
                      {u.has_own_key ? (
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                          自填Key
                        </span>
                      ) : (
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                          平台Key
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 tabular-nums text-slate-800">{u.platform_quota}</td>
                  <td className="px-3 py-2.5 tabular-nums text-slate-700">{u.interview_count}</td>
                  <td className="px-3 py-2.5 text-xs text-slate-500">{fmtTime(u.last_active_at)}</td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-10 text-center text-slate-500">
                    暂无用户
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selected && <aside className="w-full shrink-0 rounded-xl border border-slate-200 bg-white p-5 xl:w-[360px]">
          <div className="flex flex-col gap-4">
            <div>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-lg font-semibold text-slate-900">{selected.username}</div>
                  <div className="mt-0.5 text-xs text-slate-500">
                    #{selected.id} · 注册 {fmtTime(selected.created_at)}
                  </div>
                </div>
                <button
                  type="button"
                  className="text-xs text-slate-500 hover:text-slate-700"
                  onClick={() => setSelected(null)}
                >
                  关闭
                </button>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg bg-slate-50/60 px-2.5 py-2">
                  <div className="text-slate-500">剩余额度</div>
                  <div className="mt-0.5 text-base font-semibold text-slate-900">
                    {selected.platform_quota}
                  </div>
                </div>
                <div className="rounded-lg bg-slate-50/60 px-2.5 py-2">
                  <div className="text-slate-500">面试 / 花费</div>
                  <div className="mt-0.5 text-base font-semibold text-slate-900">
                    {selected.interview_count} / ¥{selected.platform_cost_yuan.toFixed(3)}
                  </div>
                </div>
              </div>
            </div>

            <section className="space-y-2">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">账号状态</div>
              <label className="flex items-center gap-2 text-xs text-slate-500">
                <input type="checkbox" checked={selected.is_test} disabled={busy} onChange={e => {
                  const checked = e.target.checked;
                  void run(async () => {
                    await api(`/api/admin/users/${selected.id}`, { method: "PATCH", body: JSON.stringify({ is_test: checked }) });
                    await refreshSelected(selected.id);
                  }, checked ? "已标记为测试账号，运营分析将排除该账号" : "已恢复为业务账号");
                }} />测试账号（排除运营统计）
              </label>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await api(`/api/admin/users/${selected.id}`, {
                        method: "PATCH",
                        body: JSON.stringify({ is_disabled: !selected.is_disabled }),
                      });
                      await refreshSelected(selected.id);
                    }, selected.is_disabled ? "已启用账号" : "已禁用账号")
                  }
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                    selected.is_disabled
                      ? "bg-emerald-700 text-white hover:bg-emerald-600"
                      : "bg-red-800 text-white hover:bg-red-700"
                  }`}
                >
                  {selected.is_disabled ? "启用账号" : "禁用账号"}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await api(`/api/admin/users/${selected.id}`, {
                        method: "PATCH",
                        body: JSON.stringify({ is_admin: !selected.is_admin }),
                      });
                      await refreshSelected(selected.id);
                    }, selected.is_admin ? "已取消管理员" : "已设为管理员")
                  }
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-800 hover:border-violet-400"
                >
                  {selected.is_admin ? "取消管理员" : "设为管理员"}
                </button>
                <button
                  type="button"
                  disabled={busy || !selected.has_own_key}
                  onClick={() =>
                    run(async () => {
                      await api(`/api/admin/users/${selected.id}/clear-llm-key`, {
                        method: "POST",
                      });
                      await refreshSelected(selected.id);
                    }, "已清除用户 API Key")
                  }
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-800 hover:border-violet-400 disabled:opacity-40"
                >
                  清除 API Key
                </button>
              </div>
            </section>

            <section className="space-y-2">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">额度</div>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[11px] text-slate-500">
                  增减（可负）
                  <input
                    value={quotaDelta}
                    onChange={(e) => setQuotaDelta(e.target.value)}
                    className={`mt-1 ${inputCls}`}
                  />
                </label>
                <label className="text-[11px] text-slate-500">
                  设为绝对值
                  <input
                    value={quotaSet}
                    onChange={(e) => setQuotaSet(e.target.value)}
                    className={`mt-1 ${inputCls}`}
                  />
                </label>
              </div>
              <input
                value={quotaNote}
                onChange={(e) => setQuotaNote(e.target.value)}
                placeholder="备注（可选）"
                className={inputCls}
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      const delta = Number(quotaDelta);
                      if (!Number.isFinite(delta) || delta === 0) throw new Error("增减次数无效");
                      await api(`/api/admin/users/${selected.id}/quota`, {
                        method: "POST",
                        body: JSON.stringify({ delta, note: quotaNote }),
                      });
                      await refreshSelected(selected.id);
                    }, "额度已增减")
                  }
                  className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-500"
                >
                  增减额度
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      const v = Number(quotaSet);
                      if (!Number.isFinite(v) || v < 0) throw new Error("额度必须 ≥ 0");
                      await api(`/api/admin/users/${selected.id}`, {
                        method: "PATCH",
                        body: JSON.stringify({ platform_quota: v }),
                      });
                      await refreshSelected(selected.id);
                    }, "额度已设置")
                  }
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-800 hover:border-violet-400"
                >
                  设为绝对值
                </button>
              </div>
            </section>

            <section className="space-y-2">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">重置密码</div>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="新密码至少 6 位"
                className={inputCls}
              />
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    if (newPassword.length < 6) throw new Error("密码至少 6 位");
                    await api(`/api/admin/users/${selected.id}/reset-password`, {
                      method: "POST",
                      body: JSON.stringify({ new_password: newPassword }),
                    });
                    setNewPassword("");
                  }, "密码已重置")
                }
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-800 hover:border-violet-400"
              >
                确认重置
              </button>
            </section>

            <section className="space-y-2">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                最近面试
              </div>
              <div className="max-h-36 space-y-1 overflow-auto text-xs text-slate-600">
                {(selected.recent_sessions || []).length === 0 && <div>暂无</div>}
                {(selected.recent_sessions || []).map((s) => (
                  <div key={s.id} className="flex justify-between gap-2 rounded bg-slate-50/50 px-2 py-1">
                    <span>
                      #{s.id} {s.mode}/{s.type} · {s.status}
                    </span>
                    <span className="shrink-0 text-slate-400">{fmtTime(s.started_at)}</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="space-y-2">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                额度变动
              </div>
              <div className="max-h-36 space-y-1 overflow-auto text-xs text-slate-600">
                {(selected.quota_grants || []).length === 0 && <div>暂无</div>}
                {(selected.quota_grants || []).map((g) => (
                  <div key={g.id} className="flex justify-between gap-2 rounded bg-slate-50/50 px-2 py-1">
                    <span>
                      {g.delta > 0 ? "+" : ""}
                      {g.delta} {g.note ? `· ${g.note}` : ""}
                    </span>
                    <span className="shrink-0 text-slate-400">{fmtTime(g.created_at)}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>
      </aside>}
    </div>
  );
}
