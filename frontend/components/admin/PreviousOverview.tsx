"use client";

// 指标改造前的概览布局，用于本地对照；数据继续使用当前后端。
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AdminIcon, EmptyState, PageHeading, SessionStatus, formatTime, type IconName } from "./AdminUI";
import { api } from "@/lib/api";
import type { AdminPage, AdminSession } from "@/lib/admin-types";
import s from "@/app/admin/admin.module.css";

type Stats = { total_users: number; disabled_users: number; dau: number; mau: number; total_interviews: number; interviews_today: number; interviews_month: number; platform_cost_yuan: number; quota_granted_total: number; error_log_count: number };
type ReviewStats = { pending: number; today_new: number };
const shortcuts: { href: string; title: string; hint: string; icon: IconName }[] = [
  { href: "/admin/users", title: "用户管理", hint: "账号、权限与面试额度", icon: "users" },
  { href: "/admin/usage", title: "用量明细", hint: "模型调用与成本追踪", icon: "usage" },
  { href: "/admin/observability", title: "运行监控", hint: "节点耗时与会话追踪", icon: "activity" },
];

export default function PreviousOverview() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [sessions, setSessions] = useState<AdminPage<AdminSession> | null>(null);
  const [reviews, setReviews] = useState<ReviewStats | null>(null);
  const [health, setHealth] = useState<boolean | null>(null);
  const [database, setDatabase] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState("");

  const load = useCallback(async () => {
    setBusy(true); setError("");
    const [statsRes, sessionsRes, reviewRes, healthRes, dbRes] = await Promise.allSettled([
      api<Stats>("/api/admin/stats"), api<AdminPage<AdminSession>>("/api/admin/sessions?limit=5"),
      api<ReviewStats>("/api/admin/tag-mismatches/stats"), api("/api/health"), api("/api/ready"),
    ]);
    if (statsRes.status === "fulfilled") setStats(statsRes.value);
    if (sessionsRes.status === "fulfilled") setSessions(sessionsRes.value);
    if (reviewRes.status === "fulfilled") setReviews(reviewRes.value);
    setHealth(healthRes.status === "fulfilled"); setDatabase(dbRes.status === "fulfilled");
    const failed = [statsRes, sessionsRes, reviewRes].find(r => r.status === "rejected");
    if (failed?.status === "rejected") setError(`部分数据加载失败：${failed.reason instanceof Error ? failed.reason.message : "请稍后刷新"}`);
    setUpdated(new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date()));
    setBusy(false);
  }, []);
  useEffect(() => { void load(); }, [load]);

  return <div className={s.page}>
    <div className={s.comparisonNotice}><span><strong>指标改造前 · 布局对照</strong>恢复上一次的概览布局，数据共用当前后端；明细页为当前版本。</span><Link href="/admin" className={s.textLink}>查看新版分析<AdminIcon name="arrow" /></Link></div>
    <PageHeading title="运营概览" description="用户、面试与平台运行情况，一目了然。">
      <span className={s.date}>{updated ? `更新于 ${updated}` : "正在同步"}</span>
      <button className={s.button} onClick={() => void load()} disabled={busy}><AdminIcon name="refresh" />{busy ? "同步中" : "刷新数据"}</button>
      <Link className={`${s.button} ${s.primaryButton}`} href="/admin/sessions">查看面试会话<AdminIcon name="arrow" /></Link>
    </PageHeading>
    {error && <div role="alert" className={s.error}>{error}</div>}
    <div className={s.metrics}>
      <Metric label="累计用户" icon="users" value={stats?.total_users} hint={<>禁用账号 <b>{stats?.disabled_users ?? "—"}</b></>} />
      <Metric label="累计面试" icon="sessions" value={stats?.total_interviews} hint={<>今日 <b>{stats?.interviews_today ?? "—"}</b> · 本月 <b>{stats?.interviews_month ?? "—"}</b></>} />
      <Metric label="月活跃用户" icon="activity" value={stats?.mau} hint={<>今日活跃 <b>{stats?.dau ?? "—"}</b></>} />
      <Metric label="平台累计支出" icon="usage" value={stats ? stats.platform_cost_yuan.toFixed(4) : undefined} money hint={<>累计发放 <b>{stats?.quota_granted_total ?? "—"}</b> 次面试额度</>} />
    </div>
    <div className={s.overviewGrid}>
      <div className={s.stack}>
        <section className={s.panel}>
          <div className={s.panelHeader}><div><h2>近期面试</h2><p>查看用户的最近练习与会话状态</p></div><Link href="/admin/sessions" className={s.textLink}>全部会话<AdminIcon name="arrow" /></Link></div>
          <div className={s.tableWrap}><table className={s.table}><thead><tr><th>会话 / 用户</th><th>目标岗位</th><th>状态</th><th>开始时间</th><th /></tr></thead><tbody>
            {sessions?.items.map(row => <tr key={row.id}><td><strong>面试 #{row.id}</strong><small>{row.username}</small></td><td>{row.target_role || "未指定"}</td><td><SessionStatus status={row.status} /></td><td>{formatTime(row.started_at, true)}</td><td><Link className={s.textLink} href={`/admin/observability/sessions/${row.id}`}>详情</Link></td></tr>)}
            {!sessions?.items.length && <tr><td colSpan={5} className={s.emptyCell}><EmptyState title={busy ? "正在加载会话" : sessions ? "还没有面试记录" : "会话暂时无法加载"} description={sessions ? "用户完成第一次面试后，会话会显示在这里。" : "请确认服务连接正常后刷新数据。"} /></td></tr>}
          </tbody></table></div>
          <div className={s.sessionFooter}><span>共 {sessions?.total ?? "—"} 场面试</span><span>北京时间 · 最近 5 条</span></div>
        </section>
        <section className={s.panel}><div className={s.panelHeader}><div><h2>常用操作</h2><p>快速进入日常管理</p></div></div><div className={s.quickLinks}>{shortcuts.map(item => <Link key={item.href} href={item.href} className={s.quickLink}><AdminIcon name={item.icon} /><span><strong>{item.title}</strong><small>{item.hint}</small></span><AdminIcon name="arrow" /></Link>)}</div></section>
      </div>
      <div className={s.stack}>
        <section className={s.panel}><div className={s.panelHeader}><h2>需要关注</h2><span className={s.badge}>待办事项</span></div>
          <Link href="/admin/tag-mismatches" className={s.taskRow}><span className={s.taskIcon}><AdminIcon name="review" /></span><span><strong>待审核题目</strong><small>今日新增 {reviews?.today_new ?? "—"} 条</small></span><b className={s.taskCount}>{reviews?.pending ?? "—"}</b><span className={s.taskArrow}>›</span></Link>
          <Link href="/admin/logs" className={s.taskRow}><span className={s.taskIcon}><AdminIcon name="logs" /></span><span><strong>系统错误</strong><small>查看错误详情与处理记录</small></span><b className={s.taskCount}>{stats?.error_log_count ?? "—"}</b><span className={s.taskArrow}>›</span></Link>
        </section>
        <section className={s.panel}><div className={s.panelHeader}><h2>运行状态</h2><Link href="/admin/observability" className={s.textLink}>查看监控</Link></div><div className={s.statusList}><Status label="后端服务" value={health} /><Status label="数据库连接" value={database} /><div className={s.statusRow}><span>数据来源</span><span className={s.statusMuted}>当前连接的数据库</span></div><div className={s.statusRow}><span>统计时区</span><span className={s.statusMuted}>Asia / Shanghai</span></div></div></section>
        <div className={s.note}><AdminIcon name="check" /><span>数据来自当前环境的实际记录。暂无数据的模块会在产生使用记录后自动更新。</span></div>
      </div>
    </div>
  </div>;
}

function Metric({ label, value, hint, icon, money }: { label: string; value?: string | number; hint: React.ReactNode; icon: IconName; money?: boolean }) {
  return <section className={s.metric}><div className={s.metricLabel}>{label}<span className={s.metricIcon}><AdminIcon name={icon} /></span></div><div className={s.metricValue}>{money && <span>¥</span>}{value ?? "—"}</div><div className={s.metricHint}>{hint}</div></section>;
}
function Status({ label, value }: { label: string; value: boolean | null }) {
  return <div className={s.statusRow}><span>{label}</span><span className={`${s.statusValue} ${value === false ? s.statusBad : value === null ? s.statusMuted : ""}`}><i />{value === null ? "检测中" : value ? "运行正常" : "连接异常"}</span></div>;
}
