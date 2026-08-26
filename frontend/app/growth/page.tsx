"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import GrowthLineChart from "@/components/GrowthLineChart";
import RadarChart from "@/components/RadarChart";
import { useToast } from "@/components/Toast";
import {
  Badge,
  ButtonLink,
  Card,
  EmptyState,
  ErrorBanner,
  IconArrowRight,
  IconReport,
  IconTarget,
  btnCls,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";

type GrowthPoint = {
  session_id: number;
  mode: string;
  type: string;
  started_at: string | null;
  overall: number | null;
  dimensions: Record<string, number>;
  weaknesses: string[];
  strengths: string[];
};

type Comparison = {
  from_session_id: number;
  to_session_id: number;
  from_at: string | null;
  to_at: string | null;
  overall_delta: number | null;
  dimension_delta: Record<string, number>;
  improved: string[];
  declined: string[];
  new_gaps: string[];
};

type PracticeSuggestion = {
  id: string;
  kind: string;
  title: string;
  reason: string;
  interview_mode: string;
  interview_type: string;
  practice_focus: string;
  priority: number;
};

type SkillTag = {
  tag: string;
  count: number;
  session_count: number;
  examples: string[];
  interview_mode: string;
  interview_type: string;
  practice_focus: string;
};

type GrowthRes = {
  session_count: number;
  points: GrowthPoint[];
  comparisons: Comparison[];
  recurring_gaps: { text: string; count: number }[];
  dimension_progress: {
    dimension: string;
    first: number | null;
    latest: number | null;
    delta: number | null;
  }[];
  recency_dimensions?: Record<string, number | null>;
  skill_tags?: SkillTag[];
  practice_suggestions?: PracticeSuggestion[];
  summary: {
    first_overall: number | null;
    latest_overall: number | null;
    total_delta: number | null;
    readiness?: number | null;
    primary_role?: string;
    trend: string;
  };
  weekly_stats?: { this_week: number; last_week: number; delta: number };
  milestones?: { id: string; title: string; desc: string }[];
  focus_dimension?: { dimension: string; score: number } | null;
  practice_streak_days?: number;
};

type Insight = {
  headline: string;
  progress: string[];
  gaps: string[];
  next_focus: string[];
};

const DIM_COLORS: Record<string, string> = {
  技术深度: "#0284c7",
  项目经验: "#059669",
  沟通表达: "#7c3aed",
  综合素质: "#ea580c",
  综合评分: "#0f172a",
};

function shortDate(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function deltaText(v: number | null | undefined) {
  if (v == null) return "-";
  if (v > 0) return `+${v.toFixed(1)}`;
  return v.toFixed(1);
}

function trendLabel(trend: string) {
  if (trend === "up") return "整体上升";
  if (trend === "down") return "整体回落";
  if (trend === "flat") return "基本持平";
  return "样本不足";
}

function practiceHref(s: PracticeSuggestion | SkillTag, title?: string) {
  const params = new URLSearchParams();
  params.set("mode", s.interview_mode || "full");
  params.set("type", s.interview_type || "full");
  if (s.practice_focus) params.set("focus", s.practice_focus);
  if (title || ("title" in s ? s.title : s.tag)) {
    params.set("from", title || ("title" in s ? s.title : s.tag));
  }
  return `/interview/new?${params.toString()}`;
}

export default function GrowthPage() {
  const toast = useToast();
  const [data, setData] = useState<GrowthRes | null>(null);
  const [error, setError] = useState("");
  const [insight, setInsight] = useState<Insight | null>(null);
  const [insightLoading, setInsightLoading] = useState(false);

  const load = useCallback(() => {
    setError("");
    api<GrowthRes>("/api/interview/growth")
      .then(setData)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          window.location.assign("/login");
        } else {
          setError(e instanceof Error ? e.message : "加载失败");
        }
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const chart = useMemo(() => {
    if (!data?.points?.length) return null;
    const labels = data.points.map((p, i) => `#${i + 1} ${shortDate(p.started_at)}`);
    const dimKeys = Array.from(
      new Set(data.points.flatMap((p) => Object.keys(p.dimensions || {})))
    );
    const series = [
      {
        key: "overall",
        label: "综合评分",
        color: DIM_COLORS["综合评分"],
        values: data.points.map((p) => p.overall),
      },
      ...dimKeys.map((k) => ({
        key: k,
        label: k,
        color: DIM_COLORS[k] || "#64748b",
        values: data.points.map((p) =>
          p.dimensions?.[k] == null ? null : Number(p.dimensions[k])
        ),
      })),
    ];
    return { labels, series };
  }, [data]);

  const radarData = useMemo(() => {
    const dims = data?.recency_dimensions || {};
    return Object.entries(dims)
      .filter(([, v]) => v != null)
      .map(([label, value]) => ({ label, value: Number(value) }));
  }, [data]);

  async function genInsight() {
    setInsightLoading(true);
    try {
      const res = await api<{ insight: Insight }>("/api/interview/growth/insight", {
        method: "POST",
      });
      setInsight(res.insight);
      toast.ok("成长解读已生成");
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "解读失败");
    } finally {
      setInsightLoading(false);
    }
  }

  const latestCmp = data?.comparisons?.length
    ? data.comparisons[data.comparisons.length - 1]
    : null;
  const suggestions = data?.practice_suggestions ?? [];
  const skillTags = data?.skill_tags ?? [];

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">成长档案</h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-zinc-500">
            记录每场独立模拟面试后的能力变化。主路径仍是完整模拟；下方「针对性再练」仅为可选预填，不会自动把历史塞进下一场。
          </p>
        </div>
        <div className="flex gap-2">
          <ButtonLink href="/interview/new" variant="primary" size="sm">
            再开一场独立面试
          </ButtonLink>
          <button
            type="button"
            className={btnCls("secondary", "sm")}
            disabled={insightLoading || !data?.session_count}
            onClick={genInsight}
          >
            {insightLoading ? "生成中…" : "AI 成长解读"}
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={load} />}

      {!error && data === null && (
        <div className="flex flex-1 items-center justify-center py-20 text-sm text-zinc-400">
          <span className="typing-dot" />
          <span className="typing-dot" />
          <span className="typing-dot" />
          <span className="ml-2">加载成长档案</span>
        </div>
      )}

      {data && data.session_count === 0 && (
        <EmptyState
          icon={<IconTarget className="h-10 w-10" />}
          title="还没有成长数据"
          desc="完成至少一场带报告的独立模拟面试后，这里会沉淀你的能力档案"
          action={<ButtonLink href="/interview/new">开始第一场</ButtonLink>}
        />
      )}

      {data && data.session_count > 0 && (
        <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {[
              { label: "已复盘场次", value: String(data.session_count) },
              {
                label: "准备度",
                value:
                  data.summary.readiness == null
                    ? "-"
                    : `${data.summary.readiness}`,
              },
              {
                label: "本周练习",
                value: String(data.weekly_stats?.this_week ?? 0),
              },
              {
                label: "连续练习天",
                value: String(data.practice_streak_days ?? 0),
              },
              {
                label: "最近综合分",
                value:
                  data.summary.latest_overall == null
                    ? "-"
                    : data.summary.latest_overall.toFixed(1),
              },
            ].map((s) => (
              <Card key={s.label} className="p-4">
                <div className="text-xs text-zinc-400">{s.label}</div>
                <div className="mt-1 text-lg font-semibold text-zinc-900">{s.value}</div>
              </Card>
            ))}
          </section>

          {(data.milestones?.length || data.focus_dimension) && (
            <section className="grid gap-4 lg:grid-cols-2">
              {data.milestones && data.milestones.length > 0 ? (
                <Card className="p-5">
                  <h2 className="text-sm font-semibold text-zinc-900">练习里程碑</h2>
                  <ul className="mt-3 space-y-2">
                    {data.milestones.map((m) => (
                      <li
                        key={m.id}
                        className="rounded-xl border border-emerald-100 bg-emerald-50/50 px-3 py-2.5"
                      >
                        <div className="text-sm font-medium text-emerald-900">{m.title}</div>
                        <div className="mt-0.5 text-xs text-emerald-800/80">{m.desc}</div>
                      </li>
                    ))}
                  </ul>
                </Card>
              ) : null}
              {data.focus_dimension ? (
                <Card className="border-amber-100 bg-amber-50/40 p-5">
                  <h2 className="text-sm font-semibold text-zinc-900">当前优先拉升维度</h2>
                  <p className="mt-2 text-2xl font-semibold text-amber-800">
                    {data.focus_dimension.dimension}
                    <span className="ml-2 text-base font-normal text-amber-700">
                      {data.focus_dimension.score}/10
                    </span>
                  </p>
                  <p className="mt-2 text-xs leading-5 text-zinc-600">
                    基于近 5 场加权画像，该维度相对最弱。可从下方「可选：下一场练什么」一键预填专场。
                  </p>
                  {data.weekly_stats ? (
                    <p className="mt-3 text-xs text-zinc-500">
                      本周 {data.weekly_stats.this_week} 场 · 上周 {data.weekly_stats.last_week} 场
                      {data.weekly_stats.delta !== 0
                        ? `（${data.weekly_stats.delta > 0 ? "+" : ""}${data.weekly_stats.delta}）`
                        : ""}
                    </p>
                  ) : null}
                </Card>
              ) : null}
            </section>
          )}

          {suggestions.length > 0 && (
            <Card className="border-sky-100 bg-gradient-to-br from-sky-50/80 to-white p-5">
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-zinc-900">可选：下一场练什么</h2>
                <Badge tone="sky">预填开练 · 仍是独立面试</Badge>
              </div>
              <p className="mb-4 text-xs leading-5 text-zinc-500">
                点选后仅预填模式与本场焦点，需你确认才开练；不自动继承历史对话。
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                {suggestions.map((s) => (
                  <Link
                    key={s.id}
                    href={practiceHref(s)}
                    className="group rounded-2xl border border-sky-100 bg-white p-4 transition hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-md hover:shadow-sky-900/5"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="text-sm font-semibold text-zinc-900">{s.title}</div>
                      <IconArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-sky-500 opacity-60 transition group-hover:translate-x-0.5 group-hover:opacity-100" />
                    </div>
                    <p className="mt-1.5 text-xs leading-5 text-zinc-500">{s.reason}</p>
                    {s.practice_focus ? (
                      <p className="mt-2 line-clamp-2 text-[11px] leading-4 text-sky-700/80">
                        焦点：{s.practice_focus}
                      </p>
                    ) : null}
                  </Link>
                ))}
              </div>
            </Card>
          )}

          <section className="grid gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-zinc-900">近因能力画像</h2>
                <Badge tone="zinc">近 5 场加权</Badge>
              </div>
              {radarData.length >= 3 ? (
                <div className="flex justify-center">
                  <RadarChart data={radarData} size={280} />
                </div>
              ) : (
                <p className="py-8 text-center text-sm text-zinc-400">维度数据不足</p>
              )}
            </Card>

            <Card className="p-5">
              <h2 className="text-sm font-semibold text-zinc-900">短板标签</h2>
              <p className="mt-1 text-xs text-zinc-400">从反复出现的欠缺归类，可一键开针对性专场</p>
              {skillTags.length === 0 ? (
                <p className="mt-6 text-sm text-zinc-400">暂无稳定短板标签</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {skillTags.map((t) => (
                    <li
                      key={t.tag}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-zinc-100 px-3 py-2.5"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-zinc-800">{t.tag}</span>
                          <Badge tone="amber">{t.count} 次</Badge>
                        </div>
                        {t.examples[0] ? (
                          <p className="mt-1 truncate text-xs text-zinc-400">{t.examples[0]}</p>
                        ) : null}
                      </div>
                      <Link
                        href={practiceHref(t, `补强：${t.tag}`)}
                        className="shrink-0 text-xs font-medium text-sky-700 hover:text-sky-800"
                      >
                        针对性再练 →
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </section>

          <Card className="p-5">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-zinc-900">能力随时间变化</h2>
              <Badge tone="sky">按完成顺序</Badge>
            </div>
            {chart && <GrowthLineChart labels={chart.labels} series={chart.series} />}
          </Card>

          <section className="grid gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <h2 className="text-sm font-semibold text-zinc-900">维度首末对比</h2>
              <ul className="mt-3 space-y-2">
                {data.dimension_progress.map((d) => (
                  <li
                    key={d.dimension}
                    className="flex items-center justify-between rounded-xl border border-zinc-100 px-3 py-2 text-sm"
                  >
                    <span className="font-medium text-zinc-800">{d.dimension}</span>
                    <span className="text-zinc-500">
                      {d.first?.toFixed?.(1) ?? "-"} → {d.latest?.toFixed?.(1) ?? "-"}
                      <span
                        className={`ml-2 font-semibold ${
                          (d.delta ?? 0) > 0
                            ? "text-emerald-600"
                            : (d.delta ?? 0) < 0
                              ? "text-red-500"
                              : "text-zinc-400"
                        }`}
                      >
                        {deltaText(d.delta)}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </Card>

            <Card className="p-5">
              <h2 className="text-sm font-semibold text-zinc-900">反复出现的原句欠缺</h2>
              {data.recurring_gaps.length === 0 ? (
                <p className="mt-3 text-sm text-zinc-400">暂无重复短板统计</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {data.recurring_gaps.map((g) => (
                    <li
                      key={g.text}
                      className="rounded-xl border border-amber-100 bg-amber-50/50 px-3 py-2 text-sm text-slate-700"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="min-w-0 flex-1">{g.text}</span>
                        <Badge tone="amber">{g.count} 次</Badge>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </section>

          {latestCmp && (
            <Card className="p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-zinc-900">
                  最近一场相对上一场
                </h2>
                <span className="text-xs text-zinc-400">
                  {shortDate(latestCmp.from_at)} → {shortDate(latestCmp.to_at)} · 综合{" "}
                  <span
                    className={
                      (latestCmp.overall_delta ?? 0) > 0
                        ? "font-semibold text-emerald-600"
                        : (latestCmp.overall_delta ?? 0) < 0
                          ? "font-semibold text-red-500"
                          : "text-zinc-500"
                    }
                  >
                    {deltaText(latestCmp.overall_delta)}
                  </span>
                </span>
              </div>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div>
                  <div className="text-xs font-semibold text-emerald-700">进步维度</div>
                  {latestCmp.improved.length === 0 ? (
                    <p className="mt-1 text-sm text-zinc-400">本场无明显上升维度</p>
                  ) : (
                    <ul className="mt-1 space-y-1 text-sm text-zinc-700">
                      {latestCmp.improved.map((k) => (
                        <li key={k}>
                          {k}{" "}
                          <span className="text-emerald-600">
                            {deltaText(latestCmp.dimension_delta[k])}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div>
                  <div className="text-xs font-semibold text-red-600">回落 / 仍需注意</div>
                  {latestCmp.declined.length === 0 && latestCmp.new_gaps.length === 0 ? (
                    <p className="mt-1 text-sm text-zinc-400">本场没有明显回落</p>
                  ) : (
                    <ul className="mt-1 space-y-1 text-sm text-zinc-700">
                      {latestCmp.declined.map((k) => (
                        <li key={k}>
                          {k}{" "}
                          <span className="text-red-500">
                            {deltaText(latestCmp.dimension_delta[k])}
                          </span>
                        </li>
                      ))}
                      {latestCmp.new_gaps.map((g) => (
                        <li key={g} className="text-slate-600">
                          · {g}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
              <div className="mt-4">
                <Link
                  href={`/report/${latestCmp.to_session_id}`}
                  className="inline-flex items-center gap-1 text-sm font-medium text-sky-700 hover:text-sky-800"
                >
                  查看本场完整报告 <IconArrowRight className="h-3.5 w-3.5" />
                </Link>
              </div>
            </Card>
          )}

          {data.comparisons.length > 1 && (
            <Card className="p-5">
              <h2 className="text-sm font-semibold text-zinc-900">场次递进记录</h2>
              <ul className="mt-3 divide-y divide-zinc-100">
                {data.comparisons
                  .slice()
                  .reverse()
                  .map((c) => (
                    <li
                      key={`${c.from_session_id}-${c.to_session_id}`}
                      className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm"
                    >
                      <div className="text-zinc-600">
                        {shortDate(c.from_at)} → {shortDate(c.to_at)}
                        {c.improved[0] ? (
                          <span className="ml-2 text-emerald-600">↑{c.improved[0]}</span>
                        ) : null}
                        {c.declined[0] ? (
                          <span className="ml-2 text-red-500">↓{c.declined[0]}</span>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-3">
                        <span
                          className={
                            (c.overall_delta ?? 0) > 0
                              ? "font-semibold text-emerald-600"
                              : (c.overall_delta ?? 0) < 0
                                ? "font-semibold text-red-500"
                                : "text-zinc-400"
                          }
                        >
                          综合 {deltaText(c.overall_delta)}
                        </span>
                        <Link
                          href={`/report/${c.to_session_id}`}
                          className="text-sky-600 hover:underline"
                        >
                          报告
                        </Link>
                      </div>
                    </li>
                  ))}
              </ul>
            </Card>
          )}

          {insight && (
            <Card className="border-sky-100 bg-sky-50/40 p-5">
              <div className="flex items-center gap-2 text-sm font-semibold text-sky-900">
                <IconReport className="h-4 w-4" />
                AI 成长解读
              </div>
              <p className="mt-2 text-sm leading-7 text-slate-700">{insight.headline}</p>
              <div className="mt-4 grid gap-4 sm:grid-cols-3">
                {(
                  [
                    { title: "进步", items: insight.progress },
                    { title: "仍需加强", items: insight.gaps },
                    { title: "可选练习方向", items: insight.next_focus },
                  ] as const
                ).map((block) => (
                  <div key={block.title}>
                    <div className="text-xs font-semibold text-slate-500">{block.title}</div>
                    <ul className="mt-1.5 list-disc space-y-1 pl-4 text-sm text-slate-700">
                      {block.items.map((it) => (
                        <li key={it}>{it}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
