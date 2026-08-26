"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import RadarChart from "@/components/RadarChart";
import MarkdownRenderer from "@/components/MarkdownRenderer";
import { Badge, Card, ErrorBanner, IconSparkles } from "@/components/ui";
import { API_BASE, ApiError, api, getToken } from "@/lib/api";

type PerQuestion = {
  topic: string;
  question: string;
  my_answers: string[];
  score: number;
  strengths: string[];
  weaknesses: string[];
  feedback: string;
  reference_answer: string;
  is_followup?: boolean;
  original_company?: string;
};

type ReportData = {
  dimension_scores: Record<string, number>;
  per_question?: PerQuestion[];
  summary: string;
  strengths: string[];
  weaknesses: string[];
  suggestions: string[];
};

type ReportRes = {
  session_id: number;
  mode: string;
  type: string;
  report: ReportData;
};

const MODE_LABEL: Record<string, string> = {
  full: "全流程混合面",
  project: "项目深挖专场",
  ba_gu: "八股专场",
  hr: "HR 行为面专场",
};

function scoreColor(v: number): string {
  return v >= 8
    ? "text-emerald-600"
    : v >= 6
      ? "text-amber-600"
      : "text-red-600";
}

function QuestionDetailModal({
  q,
  index,
  onClose,
}: {
  q: PerQuestion;
  index: number;
  onClose: () => void;
}) {
  const [showRef, setShowRef] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (showRef) setShowRef(false);
      else onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose, showRef]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 print:hidden">
      <button
        type="button"
        aria-label="关闭"
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        className="animate-fade-up relative z-10 flex max-h-[85vh] w-full max-w-xl flex-col overflow-hidden rounded-3xl border border-sky-100 bg-white shadow-2xl shadow-sky-900/15"
      >
        <div className="flex items-start gap-3 border-b border-sky-50 px-6 py-5">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sky-100 text-sm font-semibold text-sky-700">
            {index + 1}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold text-slate-900">{q.topic}</h3>
              {q.is_followup ? (
                <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                  追问
                </span>
              ) : null}
              {q.original_company ? (
                <span className="inline-flex items-center gap-0.5 rounded-full bg-gradient-to-r from-amber-400 to-orange-400 px-2 py-0.5 text-[11px] font-semibold text-white shadow-sm">
                  ★ {q.original_company} 原题
                </span>
              ) : null}
            </div>
            <p className={`mt-1 text-sm font-semibold ${scoreColor(q.score)}`}>
              {q.score}/10
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-700"
            aria-label="关闭"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5 text-sm">
          <div>
            <div className="mb-1.5 text-xs font-medium text-slate-400">问题</div>
            <MarkdownRenderer content={q.question} className="text-slate-800" />
          </div>
          {q.my_answers.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-slate-400">我的作答</div>
              <div className="flex flex-col gap-2">
                {q.my_answers.map((a, j) => (
                  <div
                    key={j}
                    className="rounded-xl bg-sky-50/80 px-3.5 py-2.5 leading-7 text-slate-600"
                  >
                    {a}
                  </div>
                ))}
              </div>
            </div>
          )}
          {q.feedback && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-slate-400">AI 点评</div>
              <div className="leading-7 text-slate-800">
                {q.strengths.length > 0 && (
                  <span className="mr-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">
                    亮点 {q.strengths.length}
                  </span>
                )}
                {q.weaknesses.length > 0 && (
                  <span className="mr-2 inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-600">
                    待改进 {q.weaknesses.length}
                  </span>
                )}
                {q.feedback}
              </div>
              {q.strengths.length > 0 && (
                <ul className="mt-2 flex list-disc flex-col gap-1 pl-4 text-xs leading-5 text-emerald-700/90">
                  {q.strengths.map((s, j) => (
                    <li key={j}>{s}</li>
                  ))}
                </ul>
              )}
              {q.weaknesses.length > 0 && (
                <ul className="mt-2 flex list-disc flex-col gap-1 pl-4 text-xs leading-5 text-red-600/90">
                  {q.weaknesses.map((w, j) => (
                    <li key={j}>{w}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {q.reference_answer && (
            <button
              type="button"
              onClick={() => setShowRef(true)}
              className="inline-flex items-center gap-1 text-xs font-medium text-sky-700 transition hover:text-sky-600"
            >
              查看参考答案 →
            </button>
          )}
        </div>
      </div>

      {showRef && q.reference_answer ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center px-4">
          <button
            type="button"
            aria-label="关闭参考答案"
            className="absolute inset-0 bg-slate-900/35"
            onClick={() => setShowRef(false)}
          />
          <div
            role="dialog"
            aria-modal="true"
            className="animate-fade-up relative z-10 flex max-h-[80vh] w-full max-w-lg flex-col overflow-hidden rounded-3xl border border-sky-100 bg-white shadow-2xl shadow-sky-900/20"
          >
            <div className="flex items-center justify-between gap-3 border-b border-sky-50 px-5 py-4">
              <div>
                <p className="text-[11px] font-medium tracking-[0.14em] text-sky-700">REFERENCE</p>
                <h4 className="mt-0.5 text-sm font-semibold text-slate-900">参考答案</h4>
              </div>
              <button
                type="button"
                onClick={() => setShowRef(false)}
                className="rounded-lg px-2 py-1 text-sm text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                关闭
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 text-sm leading-7 text-slate-800">
              <MarkdownRenderer content={q.reference_answer} />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function ReportPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;
  const router = useRouter();
  const [data, setData] = useState<ReportRes | null>(null);
  const [error, setError] = useState("");
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const [exporting, setExporting] = useState<"docx" | "pdf" | null>(null);
  const [showTraceLink, setShowTraceLink] = useState(
    () => process.env.NODE_ENV === "development"
  );

  const load = useCallback(() => {
    setError("");
    api<ReportRes>(`/api/interview/session/${sessionId}/report`)
      .then(setData)
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
    if (process.env.NODE_ENV !== "development") {
      api<{ is_admin?: boolean }>("/api/auth/me")
        .then((me) => setShowTraceLink(!!me.is_admin))
        .catch(() => {});
    }
  }, [load, router]);

  async function exportFile(format: "docx" | "pdf") {
    setExporting(format);
    try {
      const token = getToken();
      const res = await fetch(
        `${API_BASE}/api/interview/session/${sessionId}/report/export?format=${format}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} }
      );
      if (!res.ok) {
        let detail = `导出失败 (${res.status})`;
        try {
          const j = await res.json();
          if (j.detail) detail = j.detail;
        } catch {}
        throw new Error(detail);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `interview_report_${sessionId}.${format === "pdf" ? "pdf" : "docx"}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(e instanceof Error ? e.message : "导出失败");
    }
    setExporting(null);
  }

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6">
        <ErrorBanner message={error} onRetry={load} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="flex items-center gap-2 text-sm text-zinc-400">
          <span className="typing-dot" />
          <span className="typing-dot" />
          <span className="typing-dot" />
          正在生成报告
        </div>
      </div>
    );
  }

  const r = data.report;
  const dims = Object.entries(r.dimension_scores);
  const total = dims.length ? dims.reduce((s, [, v]) => s + v, 0) / dims.length : 0;
  const perQ = r.per_question ?? [];
  const activeQ = activeIdx !== null ? perQ[activeIdx] : null;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 px-6 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">面试报告</h1>
          <div className="mt-1.5 flex items-center gap-2">
            <Badge tone="sky">
              {data.mode === "full" ? MODE_LABEL.full : MODE_LABEL[data.type] ?? data.type}
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-2 print:hidden">
          <button
            onClick={() => exportFile("docx")}
            disabled={!!exporting}
            className="rounded-xl border border-zinc-200 bg-white px-4 py-2 text-sm font-medium text-zinc-700 shadow-sm transition hover:bg-zinc-50 disabled:opacity-50"
          >
            {exporting === "docx" ? "导出中…" : "导出 Word"}
          </button>
          <button
            onClick={() => exportFile("pdf")}
            disabled={!!exporting}
            className="rounded-xl bg-sky-600 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-sky-600/25 transition hover:bg-sky-500 disabled:opacity-50"
          >
            {exporting === "pdf" ? "导出中…" : "导出 PDF"}
          </button>
        </div>
      </div>

      <div className="animate-fade-up grid gap-4 sm:grid-cols-2">
        <Card className="p-5">
          <h2 className="mb-3 text-sm font-semibold text-slate-900">能力雷达图</h2>
          <div className="flex justify-center">
            <RadarChart data={dims.map(([label, value]) => ({ label, value }))} />
          </div>
        </Card>
        <div className="flex flex-col gap-4">
          <div className="relative flex flex-1 flex-col items-center justify-center overflow-hidden rounded-2xl bg-gradient-to-br from-sky-600 to-blue-600 p-5 text-center text-white shadow-lg shadow-sky-600/25">
            <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-white/10" />
            <div className="absolute -bottom-8 -left-4 h-20 w-20 rounded-full bg-white/10" />
            <div className="flex items-center gap-1.5 text-sm text-sky-100">
              <IconSparkles className="h-4 w-4" />
              综合评分
            </div>
            <div className="mt-1 text-6xl font-bold tracking-tight">{total.toFixed(1)}</div>
            <div className="text-xs text-sky-200">满分 10 分 · 各维度加权平均</div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {dims.map(([k, v]) => (
              <Card key={k} className="p-3 text-center transition hover:-translate-y-0.5 hover:shadow-md">
                <div className="text-xs text-zinc-500">{k}</div>
                <div className={`mt-0.5 text-2xl font-semibold ${scoreColor(v)}`}>{v}</div>
              </Card>
            ))}
          </div>
        </div>
      </div>

      <Card className="animate-fade-up p-5" style={{ animationDelay: "0.08s" }}>
        <h2 className="mb-2 text-sm font-semibold text-slate-900">总体评价</h2>
        <p className="text-sm leading-7 text-slate-700">{r.summary}</p>
      </Card>

      {perQ.length > 0 && (
        <Card className="animate-fade-up p-5 print:shadow-none" style={{ animationDelay: "0.12s" }}>
          <h2 className="mb-1 text-sm font-semibold text-slate-900">逐题作答详情</h2>
          <p className="mb-3 text-xs text-slate-400">点击题目查看完整作答与点评</p>
          <div className="flex flex-col gap-2.5">
            {perQ.map((q, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setActiveIdx(i)}
                className="group flex w-full items-center gap-3 rounded-xl border border-sky-100/80 bg-white px-4 py-3 text-left transition hover:-translate-y-0.5 hover:border-sky-300 hover:bg-sky-50/60 hover:shadow-md hover:shadow-sky-900/5"
              >
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sky-100 text-xs font-semibold text-sky-700 transition group-hover:bg-sky-600 group-hover:text-white">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900">
                  {q.topic}
                  {q.is_followup ? (
                    <span className="ml-2 inline-flex rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                      追问
                    </span>
                  ) : null}
                  {q.original_company ? (
                    <span className="ml-2 inline-flex items-center gap-0.5 rounded-full bg-gradient-to-r from-amber-400 to-orange-400 px-1.5 py-0.5 text-[10px] font-semibold text-white shadow-sm">
                      ★ {q.original_company} 原题
                    </span>
                  ) : null}
                </span>
                <span className={`shrink-0 text-sm font-semibold ${scoreColor(q.score)}`}>
                  {q.score}/10
                </span>
                <svg
                  viewBox="0 0 16 16"
                  className="h-4 w-4 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-sky-500"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                >
                  <path d="M6 3h7v7M13 3 3 13" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            ))}
          </div>

          {/* 打印时展开全部详情 */}
          <div className="mt-4 hidden print:block">
            {perQ.map((q, i) => (
              <div key={i} className="mb-4 border-t border-zinc-200 pt-3 text-sm">
                <div className="font-semibold">
                  {i + 1}. {q.topic}（{q.score}/10）
                </div>
                <div className="mt-1 text-zinc-600">问：{q.question}</div>
                <div className="mt-1 text-zinc-600">答：{q.my_answers.join(" / ")}</div>
                <div className="mt-1 text-zinc-600">评：{q.feedback}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="animate-fade-up grid gap-4 sm:grid-cols-2" style={{ animationDelay: "0.16s" }}>
        <Card className="border-emerald-200/70 p-5">
          <h2 className="mb-2.5 text-sm font-semibold text-emerald-700">优点</h2>
          <ul className="flex list-disc flex-col gap-1.5 pl-4 text-sm leading-6 text-slate-700">
            {r.strengths.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </Card>
        <Card className="border-red-200/70 p-5">
          <h2 className="mb-2.5 text-sm font-semibold text-red-700">待提升</h2>
          <ul className="flex list-disc flex-col gap-1.5 pl-4 text-sm leading-6 text-slate-700">
            {r.weaknesses.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Card>
      </div>

      <Card className="animate-fade-up p-5" style={{ animationDelay: "0.2s" }}>
        <h2 className="mb-2.5 text-sm font-semibold text-slate-900">提升建议</h2>
        <ol className="flex list-decimal flex-col gap-2 pl-5 text-sm leading-6 text-slate-700">
          {r.suggestions.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      </Card>

      <div className="flex justify-center gap-3 pb-4 print:hidden">
        <Link
          href="/interview/new"
          className="rounded-xl bg-gradient-to-r from-sky-600 to-blue-600 px-6 py-2.5 text-sm font-medium text-white shadow-md shadow-sky-600/25 transition hover:from-sky-500 hover:to-blue-500"
        >
          再来一场
        </Link>
        {showTraceLink ? (
          <Link
            href={`/report/${sessionId}/trace`}
            className="rounded-xl border border-violet-200 bg-violet-50 px-6 py-2.5 text-sm font-medium text-violet-700 transition hover:bg-violet-100"
          >
            调试 Trace
          </Link>
        ) : null}
        <Link
          href="/dashboard"
          className="rounded-xl border border-zinc-200 bg-white px-6 py-2.5 text-sm text-zinc-600 transition hover:bg-zinc-50"
        >
          返回首页
        </Link>
      </div>

      {activeQ && activeIdx !== null && (
        <QuestionDetailModal q={activeQ} index={activeIdx} onClose={() => setActiveIdx(null)} />
      )}
    </div>
  );
}
