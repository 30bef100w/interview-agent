"use client";
import Link from "next/link";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AdminIcon, EmptyState, PageHeading, formatTime } from "@/components/admin/AdminUI";
import { api } from "@/lib/api";
import type { AdminPage, AdminUsage } from "@/lib/admin-types";
import s from "../admin.module.css";
type UsagePage = AdminPage<AdminUsage> & { total_cost_yuan: number };

export default function AdminUsagePage() {
  return <Suspense fallback={<div className={s.page}>正在加载用量筛选…</div>}><UsageContent /></Suspense>;
}

function UsageContent() {
  const search = useSearchParams();
  const scope = new URLSearchParams();
  for (const key of ["start_time", "end_time", "end_exclusive", "business_only", "provider"]) {
    const value = search.get(key);
    if (value) scope.set(key, value);
  }
  const scopeQuery = scope.toString();
  const [data, setData] = useState<UsagePage | null>(null);
  const [model, setModel] = useState(search.get("model") ?? "");
  const [query, setQuery] = useState(search.get("model") ?? "");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const request = useRef(0);
  const load = useCallback(async () => {
    const id = ++request.current;
    setBusy(true); setError("");
    const params = new URLSearchParams({ limit: "20", offset: String(offset) });
    new URLSearchParams(scopeQuery).forEach((value, key) => params.set(key, value));
    if (query) params.set("model", query);
    try { const result = await api<UsagePage>(`/api/admin/usage/platform?${params}`); if (id === request.current) setData(result); }
    catch (err) { if (id === request.current) { setData(null); setError(err instanceof Error ? err.message : "用量加载失败"); } }
    finally { if (id === request.current) setBusy(false); }
  }, [query, offset, scopeQuery]);
  useEffect(() => { void load(); }, [load]);
  return <div className={s.page}><PageHeading title="用量与成本" description="平台 Key 的用量记录与估算成本，按 Token 和配置单价计算。"><button className={s.button} disabled={busy} onClick={() => void load()}><AdminIcon name="refresh" />刷新</button></PageHeading>
    {scopeQuery && <div className={s.note}>沿用运营分析的日期与业务账号范围。{search.get("provider") && <span>供应商：{search.get("provider")}</span>}<Link className={s.textLink} href="/admin/usage">清除范围筛选</Link></div>}
    <div className={s.metrics}><section className={s.metric}><div className={s.metricLabel}>筛选范围估算成本<span className={s.metricIcon}><AdminIcon name="usage" /></span></div><div className={s.metricValue}><span>¥</span>{data?.total_cost_yuan.toFixed(4) ?? "—"}</div><div className={s.metricHint}>按当前日期、模型与账号范围汇总</div></section><section className={s.metric}><div className={s.metricLabel}>用量记录<span className={s.metricIcon}><AdminIcon name="activity" /></span></div><div className={s.metricValue}>{data?.total ?? "—"}</div><div className={s.metricHint}>包含输入、输出 Token 与费用</div></section></div>
    <form className={s.filters} onSubmit={e => { e.preventDefault(); setOffset(0); setQuery(model.trim()); }}><input aria-label="按模型筛选" placeholder="模型名称，例如 deepseek" className={s.input} value={model} onChange={e => setModel(e.target.value)} /><button type="submit" className={`${s.button} ${s.primaryButton}`}>筛选记录</button></form>
    {error && <div role="alert" className={s.error}>{error}</div>}
    <section className={s.panel}><div className={s.tableWrap}><table className={s.table}><thead><tr><th>模型 / 供应商</th><th>用户 ID</th><th>会话 ID</th><th>输入 Token</th><th>输出 Token</th><th>费用</th><th>调用时间</th></tr></thead><tbody>{data?.items.map(row => <tr key={row.id}><td><strong>{row.model}</strong><small>{row.provider}</small></td><td>#{row.user_id}</td><td>{row.session_id ? `#${row.session_id}` : "—"}</td><td>{row.input_tokens.toLocaleString()}</td><td>{row.output_tokens.toLocaleString()}</td><td>¥{row.cost_yuan.toFixed(4)}</td><td>{formatTime(row.created_at)}</td></tr>)}{!data?.items.length && <tr><td colSpan={7} className={s.emptyCell}><EmptyState icon="usage" title={busy ? "正在加载用量" : error ? "加载失败" : "暂无平台调用记录"} description="使用平台 Key 完成模型调用后，这里会展示用量与估算成本。" /></td></tr>}</tbody></table></div><div className={s.pager}><span>共 {data?.total ?? 0} 条</span><button className={s.button} disabled={busy || offset === 0} onClick={() => setOffset(n => Math.max(0, n - 20))}>上一页</button><button className={s.button} disabled={busy || offset + 20 >= (data?.total ?? 0)} onClick={() => setOffset(n => n + 20)}>下一页</button></div></section>
  </div>;
}
