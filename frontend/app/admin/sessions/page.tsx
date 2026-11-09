"use client";
import Link from "next/link";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AdminIcon, EmptyState, PageHeading, SessionStatus, formatTime } from "@/components/admin/AdminUI";
import { api } from "@/lib/api";
import type { AdminPage, AdminSession } from "@/lib/admin-types";
import s from "../admin.module.css";

export default function AdminSessionsPage() {
  return <Suspense fallback={<div className={s.page}>正在加载会话筛选…</div>}><SessionsContent /></Suspense>;
}

function SessionsContent() {
  const search = useSearchParams();
  const scope = new URLSearchParams();
  for (const key of ["start_time", "end_time", "end_exclusive", "business_only", "type", "mode"]) {
    const value = search.get(key);
    if (value) scope.set(key, value);
  }
  const scopeQuery = scope.toString();
  const [data, setData] = useState<AdminPage<AdminSession> | null>(null);
  const [username, setUsername] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const request = useRef(0);
  const load = useCallback(async () => {
    const id = ++request.current;
    setBusy(true); setError("");
    const params = new URLSearchParams({ limit: "20", offset: String(offset) });
    new URLSearchParams(scopeQuery).forEach((value, key) => params.set(key, value));
    if (query) params.set("username", query);
    if (status) params.set("status", status);
    try { const result = await api<AdminPage<AdminSession>>(`/api/admin/sessions?${params}`); if (id === request.current) setData(result); }
    catch (err) { if (id === request.current) { setData(null); setError(err instanceof Error ? err.message : "会话加载失败"); } }
    finally { if (id === request.current) setBusy(false); }
  }, [query, status, offset, scopeQuery]);
  useEffect(() => { void load(); }, [load]);
  return <div className={s.page}><PageHeading title="面试会话" description="查询面试记录，追踪每场面试的状态、用量记录与估算成本。"><button className={s.button} disabled={busy} onClick={() => void load()}><AdminIcon name="refresh" />刷新</button></PageHeading>
    {scopeQuery && <div className={s.note}>沿用运营分析的日期、账号范围和类型筛选。{search.get("start_time") && <span>{formatTime(search.get("start_time"), true)} 至 {formatTime(search.get("end_time"), true)}（结束时刻不含）</span>}<Link className={s.textLink} href="/admin/sessions">清除范围筛选</Link></div>}
    <form className={s.filters} onSubmit={e => { e.preventDefault(); setOffset(0); setQuery(username.trim()); }}><input aria-label="搜索用户名" className={s.input} placeholder="搜索用户名" value={username} onChange={e => setUsername(e.target.value)} /><select aria-label="会话状态" className={s.input} value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}><option value="">全部状态</option><option value="active">进行中</option><option value="finished">已完成</option><option value="creating">准备中</option><option value="failed">失败</option><option value="abandoned">已放弃</option></select><button type="submit" className={`${s.button} ${s.primaryButton}`}>搜索会话</button></form>
    {error && <div role="alert" className={s.error}>{error}</div>}
    <section className={s.panel}><div className={s.tableWrap}><table className={s.table}><thead><tr><th>会话 / 用户</th><th>目标岗位 / 企业</th><th>状态</th><th>问答数</th><th>用量记录</th><th>估算成本</th><th>开始时间</th><th>操作</th></tr></thead><tbody>{data?.items.map(row => <tr key={row.id}><td><strong>#{row.id}</strong><small>{row.username}</small></td><td><strong>{row.target_role || "未指定"}</strong><small>{row.target_company || "不限企业"}</small></td><td><SessionStatus status={row.status} /></td><td>{row.question_count} / {row.answer_count}</td><td>{row.llm_calls} 条</td><td>¥{row.cost_yuan.toFixed(4)}</td><td>{formatTime(row.started_at, true)}</td><td><Link className={s.textLink} href={`/admin/observability/sessions/${row.id}`}>查看追踪<AdminIcon name="arrow" /></Link></td></tr>)}{!data?.items.length && <tr><td colSpan={8} className={s.emptyCell}><EmptyState title={busy ? "正在加载会话" : error ? "加载失败" : "暂无匹配的面试会话"} description="可以调整筛选条件，或在用户开始面试后返回查看。" /></td></tr>}</tbody></table></div><div className={s.pager}><span>共 {data?.total ?? 0} 场</span><button className={s.button} disabled={busy || offset === 0} onClick={() => setOffset(n => Math.max(0, n - 20))}>上一页</button><button className={s.button} disabled={busy || offset + 20 >= (data?.total ?? 0)} onClick={() => setOffset(n => n + 20)}>下一页</button></div></section>
  </div>;
}
