"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorBanner, Card } from "@/components/ui";
import { api } from "@/lib/api";

type TagMismatchItem = {
  id: number;
  status: string;
  lane: string;
  target_roles: string[];
  question: string;
  tagged_roles: string[];
  tagged_scenes: string[];
  company: string;
  category: string;
  filter_reason: string;
  session_id: number | null;
  note: string;
  resolved_by: number | null;
  created_at: string;
  resolved_at: string | null;
};

type ListRes = { total: number; items: TagMismatchItem[] };
type StatsRes = { pending: number; today_new: number };

type CatalogRes = {
  roles: { id: string; name: string }[];
  companies: { id: string; name: string }[];
  business_scenes: { id: string; name: string }[];
  tech_scenes: { id: string; name: string }[];
  categories: { id: string; name: string }[];
};

type QuestionRes = {
  found: boolean;
  question: string;
  roles: string[];
  business_scene: string[];
  tech_scene: string[];
  company: string | null;
  category: string;
};

const STATUS_OPTIONS = [
  { value: "pending", label: "待处理" },
  { value: "resolved", label: "已修正" },
  { value: "dismissed", label: "已忽略" },
  { value: "", label: "全部" },
];

function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

export default function AdminTagMismatchesPage() {
  const [stats, setStats] = useState<StatsRes | null>(null);
  const [catalog, setCatalog] = useState<CatalogRes | null>(null);
  const [status, setStatus] = useState("pending");
  const [lane, setLane] = useState("");
  const [items, setItems] = useState<TagMismatchItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [editing, setEditing] = useState<TagMismatchItem | null>(null);
  const [form, setForm] = useState<QuestionRes | null>(null);
  const [formLoading, setFormLoading] = useState(false);
  const limit = 30;

  const loadStats = useCallback(() => {
    api<StatsRes>("/api/admin/tag-mismatches/stats")
      .then(setStats)
      .catch(() => {});
  }, []);

  const loadCatalog = useCallback(() => {
    api<CatalogRes>("/api/admin/question-bank/catalog")
      .then(setCatalog)
      .catch(() => {});
  }, []);

  const loadList = useCallback(() => {
    setError("");
    const qs = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (status) qs.set("status", status);
    if (lane.trim()) qs.set("lane", lane.trim());
    api<ListRes>(`/api/admin/tag-mismatches?${qs}`)
      .then((res) => {
        setItems(res.items);
        setTotal(res.total);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, [status, lane, offset]);

  useEffect(() => {
    loadStats();
    loadCatalog();
  }, [loadStats, loadCatalog]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  async function openEdit(row: TagMismatchItem) {
    setEditing(row);
    setFormLoading(true);
    try {
      const q = await api<QuestionRes>(`/api/admin/tag-mismatches/${row.id}/question`);
      setForm({
        ...q,
        roles: q.roles.length ? q.roles : row.target_roles,
      });
    } catch (e) {
      alert(e instanceof Error ? e.message : "加载题目失败");
      setEditing(null);
    } finally {
      setFormLoading(false);
    }
  }

  async function applyEdit(action: "update" | "delete") {
    if (!editing || !form) return;
    if (action === "delete") {
      if (!window.confirm("确定从题库永久删除这道题？删除后所有用户都不会再刷到。")) return;
    }
    setBusyId(editing.id);
    try {
      await api(`/api/admin/tag-mismatches/${editing.id}/apply`, {
        method: "POST",
        body: JSON.stringify({
          action,
          roles: form.roles,
          business_scene: form.business_scene,
          tech_scene: form.tech_scene,
          company: form.company,
          category: form.category || "bagu",
        }),
      });
      setEditing(null);
      setForm(null);
      loadStats();
      loadList();
    } catch (e) {
      alert(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusyId(null);
    }
  }

  async function resolveItem(id: number, next: "resolved" | "dismissed") {
    const note =
      window.prompt(next === "resolved" ? "处理备注（可选）" : "忽略原因（可选）") ?? "";
    setBusyId(id);
    try {
      await api(`/api/admin/tag-mismatches/${id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ status: next, note }),
      });
      loadStats();
      loadList();
    } catch (e) {
      alert(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusyId(null);
    }
  }

  const page = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-100">错标审核</h1>
        <p className="mt-1 text-sm text-zinc-400">
          LLM 过滤剔除的题目标签异常。可直接修改题库标签或删除题目，修改会写回 questions_dedup.jsonl。
        </p>
      </div>

      {error ? <ErrorBanner message={error} onRetry={loadList} /> : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="border-zinc-800 bg-zinc-900/60 p-4 text-zinc-100">
          <div className="text-xs text-zinc-500">待处理</div>
          <div className="mt-1 text-2xl font-semibold">{stats?.pending ?? "-"}</div>
        </Card>
        <Card className="border-zinc-800 bg-zinc-900/60 p-4 text-zinc-100">
          <div className="text-xs text-zinc-500">今日新增</div>
          <div className="mt-1 text-2xl font-semibold">{stats?.today_new ?? "-"}</div>
        </Card>
      </div>

      <Card className="border-zinc-800 bg-zinc-900/60 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm text-zinc-400">
            状态
            <select
              value={status}
              onChange={(e) => {
                setOffset(0);
                setStatus(e.target.value);
              }}
              className="mt-1 block rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value || "all"} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-zinc-400">
            通道 lane
            <input
              value={lane}
              onChange={(e) => {
                setOffset(0);
                setLane(e.target.value);
              }}
              placeholder="role_filter / scene_filter"
              className="mt-1 block w-48 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-sky-600"
            />
          </label>
          <button
            type="button"
            onClick={() => {
              loadStats();
              loadList();
            }}
            className="rounded-lg bg-zinc-800 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-700"
          >
            刷新
          </button>
        </div>
      </Card>

      <Card className="overflow-hidden border-zinc-800 bg-zinc-900/60">
        <div className="border-b border-zinc-800 px-4 py-3 text-sm text-zinc-400">
          共 {total} 条 · 第 {page}/{totalPages} 页
        </div>
        <div className="divide-y divide-zinc-800">
          {items.map((row) => (
            <div key={row.id} className="space-y-2 px-4 py-4">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono text-zinc-500">#{row.id}</span>
                <span className="rounded bg-zinc-800 px-2 py-0.5 text-zinc-300">{row.status}</span>
                <span className="rounded bg-sky-950 px-2 py-0.5 text-sky-300">{row.lane}</span>
                {row.company ? (
                  <span className="text-zinc-500">{row.company}</span>
                ) : null}
                {row.session_id ? (
                  <span className="text-zinc-600">session {row.session_id}</span>
                ) : null}
              </div>
              <p className="text-sm leading-6 text-zinc-200">{row.question}</p>
              <div className="flex flex-wrap gap-2 text-xs text-zinc-500">
                <span>目标岗：{row.target_roles.join("、") || "-"}</span>
                <span>·</span>
                <span>标注岗：{row.tagged_roles.join("、") || "-"}</span>
                {row.tagged_scenes.length > 0 ? (
                  <>
                    <span>·</span>
                    <span>场景：{row.tagged_scenes.join("、")}</span>
                  </>
                ) : null}
              </div>
              {row.filter_reason ? (
                <p className="text-xs text-amber-400/90">剔除原因：{row.filter_reason}</p>
              ) : null}
              {row.note ? <p className="text-xs text-zinc-500">备注：{row.note}</p> : null}
              {row.status === "pending" ? (
                <div className="flex flex-wrap gap-2 pt-1">
                  <button
                    type="button"
                    disabled={busyId === row.id}
                    onClick={() => void openEdit(row)}
                    className="rounded-lg bg-sky-700 px-3 py-1.5 text-xs text-white hover:bg-sky-600 disabled:opacity-50"
                  >
                    修改标签 / 删除
                  </button>
                  <button
                    type="button"
                    disabled={busyId === row.id}
                    onClick={() => void resolveItem(row.id, "dismissed")}
                    className="rounded-lg bg-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-600 disabled:opacity-50"
                  >
                    忽略（不改题库）
                  </button>
                </div>
              ) : null}
            </div>
          ))}
          {items.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-zinc-500">暂无记录</div>
          ) : null}
        </div>
        {totalPages > 1 ? (
          <div className="flex justify-center gap-2 border-t border-zinc-800 px-4 py-3">
            <button
              type="button"
              disabled={offset <= 0}
              onClick={() => setOffset((o) => Math.max(0, o - limit))}
              className="rounded-lg bg-zinc-800 px-3 py-1.5 text-sm text-zinc-300 disabled:opacity-40"
            >
              上一页
            </button>
            <button
              type="button"
              disabled={offset + limit >= total}
              onClick={() => setOffset((o) => o + limit)}
              className="rounded-lg bg-zinc-800 px-3 py-1.5 text-sm text-zinc-300 disabled:opacity-40"
            >
              下一页
            </button>
          </div>
        ) : null}
      </Card>

      {editing ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <Card className="max-h-[90vh] w-full max-w-2xl overflow-y-auto border-zinc-700 bg-zinc-900 p-5 text-zinc-100">
            <h2 className="text-lg font-semibold">编辑题库条目</h2>
            <p className="mt-2 text-sm leading-6 text-zinc-300">{editing.question}</p>
            {!form || formLoading ? (
              <p className="mt-4 text-sm text-zinc-500">加载中…</p>
            ) : (
              <div className="mt-4 space-y-4 text-sm">
                {!form.found ? (
                  <p className="text-amber-400">题库文件中未找到该题，以下标签来自审核记录。</p>
                ) : null}

                <label className="block text-zinc-400">
                  类型
                  <select
                    value={form.category || "bagu"}
                    onChange={(e) => setForm({ ...form, category: e.target.value })}
                    className="mt-1 block w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2"
                  >
                    {(catalog?.categories ?? [
                      { id: "bagu", name: "八股" },
                      { id: "project", name: "项目" },
                    ]).map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="block text-zinc-400">
                  企业
                  <select
                    value={form.company ?? ""}
                    onChange={(e) =>
                      setForm({ ...form, company: e.target.value || null })
                    }
                    className="mt-1 block w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2"
                  >
                    <option value="">无</option>
                    {(catalog?.companies ?? []).map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </label>

                <div>
                  <div className="text-zinc-400">岗位 roles</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(catalog?.roles ?? []).map((r) => (
                      <button
                        key={r.id}
                        type="button"
                        onClick={() => setForm({ ...form, roles: toggle(form.roles, r.id) })}
                        className={`rounded-full px-3 py-1 text-xs ${
                          form.roles.includes(r.id)
                            ? "bg-sky-700 text-white"
                            : "bg-zinc-800 text-zinc-300"
                        }`}
                      >
                        {r.name}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="text-zinc-400">业务场景</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(catalog?.business_scenes ?? []).map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() =>
                          setForm({
                            ...form,
                            business_scene: toggle(form.business_scene, s.id),
                          })
                        }
                        className={`rounded-full px-3 py-1 text-xs ${
                          form.business_scene.includes(s.id)
                            ? "bg-emerald-700 text-white"
                            : "bg-zinc-800 text-zinc-300"
                        }`}
                      >
                        {s.name}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="text-zinc-400">技术场景</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(catalog?.tech_scenes ?? []).map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() =>
                          setForm({ ...form, tech_scene: toggle(form.tech_scene, s.id) })
                        }
                        className={`rounded-full px-3 py-1 text-xs ${
                          form.tech_scene.includes(s.id)
                            ? "bg-violet-700 text-white"
                            : "bg-zinc-800 text-zinc-300"
                        }`}
                      >
                        {s.name}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2 border-t border-zinc-800 pt-4">
                  <button
                    type="button"
                    disabled={busyId === editing.id || form.roles.length === 0}
                    onClick={() => void applyEdit("update")}
                    className="rounded-lg bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-600 disabled:opacity-50"
                  >
                    保存到题库
                  </button>
                  <button
                    type="button"
                    disabled={busyId === editing.id}
                    onClick={() => void applyEdit("delete")}
                    className="rounded-lg bg-red-800 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-50"
                  >
                    从题库删除
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEditing(null);
                      setForm(null);
                    }}
                    className="rounded-lg bg-zinc-700 px-4 py-2 text-sm text-zinc-200"
                  >
                    取消
                  </button>
                </div>
              </div>
            )}
          </Card>
        </div>
      ) : null}
    </div>
  );
}
