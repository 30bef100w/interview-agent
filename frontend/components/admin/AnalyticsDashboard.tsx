"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AdminIcon, EmptyState, PageHeading, formatTime } from "./AdminUI";
import { api } from "@/lib/api";
import type { AdminAnalytics, AnalyticsDay, AnalyticsMetric } from "@/lib/admin-types";
import s from "@/app/admin/admin.module.css";

const typeNames: Record<string, string> = { full: "全流程面试", ba_gu: "八股专项", project: "项目专项", hr: "HR 专项" };
const metricIcons = ["users", "activity", "sessions", "check", "review", "usage"] as const;
type TrendKey = "answer_users" | "created_sessions" | "platform_cost_yuan";
const trendOptions: { key: TrendKey; label: string }[] = [
  { key: "answer_users", label: "答题用户" }, { key: "created_sessions", label: "创建面试" },
  { key: "platform_cost_yuan", label: "平台成本" },
];
const number = (value: number) => value.toLocaleString("zh-CN");
function valueText(value: number | null | undefined, unit = "count") {
  if (value == null) return "—";
  if (unit === "ratio") return `${(value * 100).toFixed(1)}%`;
  if (unit === "yuan") return `¥${value.toFixed(4)}`;
  return number(value);
}

function detailUrl(path: string, data: AdminAnalytics, extra: Record<string, string> = {}) {
  const query = new URLSearchParams({ start_time: data.period.start_time, end_time: data.period.end_time,
    end_exclusive: "true", business_only: "true", ...extra });
  return `${path}?${query}`;
}

export default function AnalyticsDashboard() {
  const [days, setDays] = useState(7);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<AdminAnalytics | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const request = useRef(0);
  // 仅保留在当前挂载的工作空间中，不写浏览器存储，也不跨账号共享。
  const cache = useRef(new Map<number, { data: AdminAnalytics; at: number }>());
  const lastRefresh = useRef(refresh);
  useEffect(() => {
    const id = ++request.current;
    const controller = new AbortController();
    const force = lastRefresh.current !== refresh;
    lastRefresh.current = refresh;
    const cached = cache.current.get(days);
    setError("");
    if (!force && cached && Date.now() - cached.at < 30_000) {
      setData(cached.data); setBusy(false);
      return () => controller.abort();
    }
    setBusy(true);
    api<AdminAnalytics>(`/api/admin/analytics?days=${days}`, { signal: controller.signal })
      .then(result => {
        if (id === request.current && !controller.signal.aborted) {
          cache.current.set(days, { data: result, at: Date.now() });
          setData(result);
        }
      })
      .catch(err => { if (!controller.signal.aborted && id === request.current) setError(err instanceof Error ? err.message : "分析数据加载失败"); })
      .finally(() => { if (!controller.signal.aborted && id === request.current) setBusy(false); });
    return () => controller.abort();
  }, [days, refresh]);

  return <div className={s.page} aria-busy={busy}>
    <PageHeading title="运营分析" description="看清使用变化、面试转化与平台成本。">
      {process.env.NODE_ENV === "development" && <Link className={s.button} href="/admin/before-metrics" target="_blank" rel="noopener">改版前对照<AdminIcon name="external" /></Link>}
      <span className={s.date}>{data ? `更新于 ${formatTime(data.as_of, true)}` : "正在同步指标"}</span>
      <button className={s.button} onClick={() => setRefresh(n => n + 1)} disabled={busy}><AdminIcon name="refresh" />刷新</button>
    </PageHeading>
    <div className={s.analyticsToolbar}>
      <div className={s.periodSwitch} role="group" aria-label="统计周期">
        {[7, 30, 90].map(period => <button key={period} aria-pressed={days === period} className={days === period ? s.periodActive : ""} onClick={() => setDays(period)}>近 {period} 天</button>)}
      </div>
      <div className={s.periodText}>{data ? <><strong>{data.period.start_date} — {data.period.end_date}</strong><span>对比 {data.period.previous_start_date} — {data.period.previous_end_date}</span></> : <span>加载完整日期与对比周期…</span>}</div>
      <span className={s.scopeBadge}><i />北京时间 · 截至昨日 · 排除管理 / 测试账号</span>
    </div>
    {data && busy && <div className={s.note} role="status">{data.period.days !== days ? `正在加载近 ${days} 天，下方暂保留近 ${data.period.days} 天的数据…` : "正在更新数据，保留上次结果供查看…"}</div>}
    {error && <div role="alert" className={s.error}>数据加载失败：{error} <button className={s.textLink} onClick={() => setRefresh(n => n + 1)}>重试</button></div>}
    <div className={s.analyticsMetrics}>
      {(data?.metrics ?? Array.from({ length: 6 }, (_, i) => ({ key: String(i), label: ["新增用户", "已答题用户", "已答题面试", "24h 面试完成率", "24h 正常报告率", "场均平台成本 · 24h"][i] }))).map((item, i) =>
        <MetricCard key={item.key} metric={"current" in item ? item as AnalyticsMetric : null} label={item.label} index={i} busy={busy}
          context={data ? ({ completion_rate: `${data.quality.completed} / ${data.quality.mature} 场 · 待观察 ${data.quality.pending}`,
            report_rate: `${data.quality.report_success} 正常 · ${data.quality.report_fallback} 兜底 · ${data.quality.report_unknown} 未知`,
            cost_per_session: `${data.quality.cost_recorded_sessions} / ${data.quality.mature} 场有平台用量记录` } as Record<string, string>)[item.key] : undefined} />)}
    </div>
      <div className={s.analyticsGrid}>
        <div className={s.stack}>
          {data && <>
          <TrendChart data={data.trend} previous={data.previous_trend} />
          <section className={s.panel}>
            <div className={s.panelHeader}><div><h2>值得关注</h2><p>根据当前数据生成，可沿明细继续核查</p></div><span className={s.badge}>数据解读</span></div>
            <div className={s.insightList}>{data.insights.length ? data.insights.map((insight, i) => <div key={i} className={`${s.insight} ${insight.tone === "warning" ? s.insightWarning : ""}`}><span>{insight.tone === "warning" ? "!" : "↗"}</span><p>{insight.text}</p></div>) : <p className={s.panelNote}>当前没有明显变化；可查看面试类型和模型成本的拆分。</p>}</div>
          </section>
          </>}
        </div>
        <div className={s.stack}>
          <RuntimeStatusCard refresh={refresh} />
          {data && <>
          <section className={s.panel}>
            <div className={s.panelHeader}><div><h2>面试转化漏斗</h2><p>同一批会话 · 创建后 24h 内</p></div><AdminIcon name="sessions" /></div>
            <div className={s.funnel}>{data.funnel.map((step, i) => <div key={step.key} className={s.funnelStep}>
              <div className={s.funnelTitle}><span><i>{String(i + 1).padStart(2, "0")}</i>{step.label}</span><strong>{number(step.count)}<small> 场</small></strong></div>
              <div className={s.funnelTrack}><div style={{ width: `${data.funnel[0].count ? step.count / data.funnel[0].count * 100 : 0}%`, opacity: 1 - i * 0.15 }} /></div>
              {i > 0 && <div className={s.funnelMeta}><span>上一步转化 {valueText(step.conversion, "ratio")}</span><span>未达此步 {step.lost} 场</span></div>}
            </div>)}</div>
            <p className={s.panelNote}>成熟会话 {data.quality.mature} 场；另有 {data.quality.pending} 场未满 24h。漏斗各步逐级取交集，首页答题数按回答发生时间统计。</p>
            {data.quality.report_unknown > 0 && <p className={s.qualityWarning}>{data.quality.report_unknown} 场报告结果未知，末步为已确认交付数量。</p>}
          </section>
          <section className={s.panel}>
            <div className={s.panelHeader}><div><h2>答题留存</h2><p>按首次答题日分群 · 自然日留存</p></div></div>
            <div className={s.retentionGrid}>{data.retention.map(row => <div key={row.day}><span>D{row.day} 留存</span><strong>{valueText(row.rate, "ratio")}</strong><small>{row.retained} / {row.eligible} 人 · 待观察 {row.pending} 人</small></div>)}</div>
            <p className={s.panelNote}>仅统计观察日已完整结束的用户；未成熟或无样本显示 —。</p>
          </section>
          </>}
        </div>
      </div>
    {data && <>
      <section className={`${s.panel} ${s.analyticsSection}`}>
        <div className={s.panelHeader}><div><h2>面试类型分析</h2><p>创建量看规模与变化；完成和退出按同一批成熟会话的 24h 结果计算</p></div><Link className={s.textLink} href={detailUrl("/admin/sessions", data)}>查看区间会话<AdminIcon name="arrow" /></Link></div>
        <div className={s.tableWrap}><table className={s.table}><thead><tr><th>面试类型</th><th>本期创建</th><th>较上期增量</th><th>成熟 / 待观察</th><th>24h 首答</th><th>24h 完成率</th><th>24h 退出率</th><th>当前失败</th><th /></tr></thead><tbody>
          {data.types.map(row => <tr key={`${row.mode}:${row.type}`}><td><strong>{typeNames[row.type] || row.type}</strong><small>{row.mode === "full" ? "全流程模式" : "专项模式"}</small></td><td>{row.created}</td><td className={row.delta > 0 ? s.positiveText : row.delta < 0 ? s.negativeText : ""}>{row.delta > 0 ? "+" : ""}{row.delta}<small>上期 {row.previous_created} 场</small></td><td>{row.mature} / {row.created - row.mature}</td><td>{row.answered}</td><td>{valueText(row.completion_rate, "ratio")}<small>{row.completed} / {row.mature} 场</small></td><td>{valueText(row.abandon_rate, "ratio")}<small>{row.abandoned} / {row.mature} 场</small></td><td>{row.failed}</td><td><Link className={s.textLink} href={detailUrl("/admin/sessions", data, { type: row.type, mode: row.mode })}>会话明细<AdminIcon name="arrow" /></Link></td></tr>)}
          {!data.types.length && <tr><td colSpan={9} className={s.emptyCell}><EmptyState title="当前区间没有业务面试" description="用户创建面试后，这里会按类型展示转化表现与变化。" /></td></tr>}
        </tbody></table></div>
      </section>
      <section className={`${s.panel} ${s.analyticsSection}`}>
        <div className={s.panelHeader}><div><h2>平台成本拆分</h2><p>按调用发生日期统计 · 供应商与模型 · 仅平台 Key</p></div><div className={s.costTotal}><span>本期估算成本</span><strong>¥{data.cost.total_yuan.toFixed(4)}</strong><Link className={s.textLink} href={detailUrl("/admin/usage", data)}>用量明细<AdminIcon name="arrow" /></Link></div></div>
        <div className={s.tableWrap}><table className={s.table}><thead><tr><th>模型 / 供应商</th><th>用量记录</th><th>输入 / 输出 Token</th><th>估算成本</th><th>成本占比</th><th /></tr></thead><tbody>
          {data.cost.models.map(row => <tr key={`${row.provider}:${row.model}`}><td><strong>{row.model}</strong><small>{row.provider}</small></td><td>{number(row.records)} 条</td><td>{number(row.input_tokens)} / {number(row.output_tokens)}</td><td>¥{row.cost_yuan.toFixed(4)}</td><td><div className={s.costShare}><span>{valueText(row.share, "ratio")}</span><i><b style={{ width: `${(row.share ?? 0) * 100}%` }} /></i></div></td><td><Link className={s.textLink} href={detailUrl("/admin/usage", data, { model: row.model, provider: row.provider })}>查看用量<AdminIcon name="arrow" /></Link></td></tr>)}
          {!data.cost.models.length && <tr><td colSpan={6} className={s.emptyCell}><EmptyState icon="usage" title="当前区间没有平台用量记录" description="供应商返回用量后，按 Token 和配置单价计算估算成本。" /></td></tr>}
        </tbody></table></div>
        <div className={s.costFootnote}>未关联会话的成本 ¥{data.cost.unassigned_yuan.toFixed(4)}，已包含在本期总额中。场均成本采用另一口径：成熟会话创建后首 24h；其中 {data.quality.cost_recorded_sessions} / {data.quality.mature} 场有平台用量记录。</div>
      </section>
      <details className={s.methodology}><summary>统计口径与数据完整性</summary><div><p>业务用户排除管理员和已标记的测试账号，保留禁用账号的历史行为。各周期采用北京时间完整日期，和前一段等长区间比较。更改测试标记会重新计算历史统计。</p><p>报告成功状态从本次改造后记录，历史未标记结果归为未知。用量记录只覆盖供应商返回的 usage，金额为配置单价下的估算，可能缺少未返回用量的调用。无记录不等于零成本。</p><p>已答题仅表示有持久化回答，包含跳过等文本，不等同于回答质量达标。当前运行监控仍为进程内样本，尚不能作为跨重启的日调用失败率或日 P95。</p></div></details>
    </>}
    {!data && busy && <div className={s.analyticsLoading} role="status">正在计算趋势、转化与成本…</div>}
  </div>;
}

function RuntimeStatusCard({ refresh }: { refresh: number }) {
  const [checks, setChecks] = useState<{ health: boolean | null; database: boolean | null }>({ health: null, database: null });
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setChecks({ health: null, database: null });
    const timeout = window.setTimeout(() => controller.abort(), 8_000);
    const probes = [
      { key: "health", path: "/api/health", expected: "ok" },
      { key: "database", path: "/api/ready", expected: "ready" },
    ] as const;
    void Promise.allSettled(probes.map(async ({ key, path, expected }) => {
      let healthy = false;
      try {
        const result = await api<{ status: string }>(path, { signal: controller.signal, cache: "no-store" });
        healthy = result.status === expected;
      } catch { /* 请求失败或超时，显示异常状态。 */ }
      if (active) setChecks(previous => ({ ...previous, [key]: healthy }));
    })).then(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [refresh]);

  return <section className={s.panel}>
    <div className={s.panelHeader}><h2>运行状态</h2><Link href="/admin/observability" className={s.textLink}>查看监控</Link></div>
    <div className={s.statusList}>
      {([ ["后端服务", checks.health], ["数据库连接", checks.database] ] as const).map(([label, value]) =>
        <div key={label} className={s.statusRow}><span>{label}</span><span className={`${s.statusValue} ${value === false ? s.statusBad : value === null ? s.statusMuted : ""}`} role="status"><i />{value === null ? "检测中" : value ? "运行正常" : "连接异常"}</span></div>)}
      <div className={s.statusRow}><span>数据来源</span><span className={s.statusMuted}>当前连接的数据库</span></div>
      <div className={s.statusRow}><span>统计时区</span><span className={s.statusMuted}>Asia / Shanghai</span></div>
    </div>
  </section>;
}

function MetricCard({ metric, label, index, busy, context }: { metric: AnalyticsMetric | null; label: string; index: number; busy: boolean; context?: string }) {
  const change = metric?.change;
  const delta = change?.value ?? 0;
  const good = metric?.better === "down" ? delta < 0 : delta > 0;
  let changeText = "暂无可比数据";
  if (change?.kind === "pp") changeText = `${delta > 0 ? "+" : ""}${delta.toFixed(1)} 个百分点`;
  if (change?.kind === "percent") changeText = `${delta > 0 ? "+" : ""}${delta.toFixed(1)}%`;
  if (change?.kind === "new") changeText = "由 0 增长";
  if (change?.kind === "unchanged") changeText = "持平";
  return <section className={s.metric}>
    <div className={s.metricLabel}><span>{label}{metric && <details className={s.metricDefinition}><summary aria-label={`${label}计算口径`}>i</summary><p>{metric.definition}</p></details>}</span><span className={s.metricIcon}><AdminIcon name={metricIcons[index]} /></span></div>
    <div className={s.metricValue}>{valueText(metric?.current, metric?.unit)}</div>
    {context && <div className={s.metricContext}>{context}</div>}
    <div className={s.metricComparison}><span className={delta !== 0 && change?.kind !== "unavailable" ? good ? s.positiveText : s.negativeText : ""}>{busy ? "计算中…" : changeText}</span><span>上期 {valueText(metric?.previous, metric?.unit)}</span></div>
  </section>;
}

function TrendChart({ data, previous }: { data: AnalyticsDay[]; previous: AnalyticsDay[] }) {
  const [key, setKey] = useState<TrendKey>("answer_users");
  const [active, setActive] = useState<number | null>(null);
  const money = key === "platform_cost_yuan";
  const max = Math.max(money ? 0.01 : 2, ...data.map(row => row[key]), ...previous.map(row => row[key]));
  const ceiling = money ? max * 1.15 : Math.ceil(max / 2) * 2;
  const x = (index: number) => 52 + (data.length > 1 ? index / (data.length - 1) : 0.5) * 630;
  const y = (value: number) => 164 - value / ceiling * 132;
  const path = (rows: AnalyticsDay[]) => rows.map((row, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(row[key])}`).join(" ");
  const index = Math.min(active ?? data.length - 1, data.length - 1);
  const selected = data[index];
  const prior = previous[index];
  const fmt = (value: number) => money ? `¥${value.toFixed(4)}` : number(value);
  return <section className={s.panel}>
    <div className={s.panelHeader}><div><h2>使用趋势</h2><p>本期与上期按第 1–{data.length} 天对齐</p></div><div className={s.chartTabs} role="group" aria-label="趋势指标">{trendOptions.map(item => <button key={item.key} aria-pressed={key === item.key} onClick={() => { setKey(item.key); setActive(null); }} className={key === item.key ? s.chartTabActive : ""}>{item.label}</button>)}</div></div>
    <div className={s.chartReadout} aria-live="polite"><span><i />本期 {selected?.date.slice(5)}<strong>{selected ? fmt(selected[key]) : "—"}</strong></span><span><i />上期 {prior?.date.slice(5)}<strong>{prior ? fmt(prior[key]) : "—"}</strong></span></div>
    <div className={s.chartWrap}><svg viewBox="0 0 720 202" role="group" aria-label={`${trendOptions.find(item => item.key === key)?.label}日趋势，支持逐日聚焦查看`}>
      {[0, 0.5, 1].map(tick => <g key={tick}><line x1="52" x2="682" y1={y(ceiling * tick)} y2={y(ceiling * tick)} stroke="#eef0f6" strokeDasharray="4 4" /><text x="42" y={y(ceiling * tick) + 4} textAnchor="end" fill="#8c98ac" fontSize="10">{money ? (ceiling * tick).toFixed(2) : ceiling * tick}</text></g>)}
      <path d={path(previous)} fill="none" stroke="#c0c8db" strokeWidth="2" strokeDasharray="5 5" />
      <path d={`${path(data)} L${x(data.length - 1)},164 L${x(0)},164 Z`} fill="#7160dc" opacity="0.06" />
      <path d={path(data)} fill="none" stroke="#7160dc" strokeWidth="2.5" strokeLinejoin="round" />
      {selected && <><line x1={x(index)} x2={x(index)} y1="24" y2="164" stroke="#c2b8f3" strokeDasharray="3 3" /><circle cx={x(index)} cy={y(selected[key])} r="4" fill="#7160dc" stroke="white" strokeWidth="2" /></>}
      {data.map((row, i) => <rect key={row.date} x={x(i) - 630 / data.length / 2} y="24" width={630 / data.length} height="145" fill="transparent" tabIndex={0} role="button" aria-label={`${row.date}，本期 ${fmt(row[key])}，上期 ${fmt(previous[i]?.[key] ?? 0)}`} onMouseEnter={() => setActive(i)} onFocus={() => setActive(i)} onClick={() => setActive(i)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setActive(i); } }}><title>{row.date}：{fmt(row[key])}</title></rect>)}
      {[0, Math.floor((data.length - 1) / 2), data.length - 1].filter((item, i, all) => all.indexOf(item) === i).map(i => <text key={i} x={x(i)} y="191" textAnchor="middle" fill="#8c98ac" fontSize="11">{data[i]?.date.slice(5)}</text>)}
    </svg></div>
    {!data.some(row => row[key]) && !previous.some(row => row[key]) && <p className={s.chartEmpty}>本期和上期均未记录该项数据</p>}
  </section>;
}
