"use client";

import { useEffect, useState } from "react";

import { useToast } from "@/components/Toast";
import { Badge, IconSparkles, btnCls } from "@/components/ui";
import { API_BASE, getToken } from "@/lib/api";

export type ResumeAnalysis = {
  summary: string;
  strengths: string[];
  risks: string[];
  improvements: string[];
  interview_focus: string[];
  score: number;
};

const SECTIONS: { key: keyof ResumeAnalysis; title: string }[] = [
  { key: "strengths", title: "优势" },
  { key: "risks", title: "风险 / 短板" },
  { key: "improvements", title: "优化建议" },
  { key: "interview_focus", title: "面试可能深挖" },
];

export default function ResumeAnalysisModal({
  open,
  resumeId,
  filename,
  analysis,
  loading,
  onClose,
}: {
  open: boolean;
  resumeId: number | null;
  filename: string;
  analysis: ResumeAnalysis | null;
  loading?: boolean;
  onClose: () => void;
}) {
  const toast = useToast();
  const [exporting, setExporting] = useState<"docx" | "pdf" | null>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function exportFile(format: "docx" | "pdf") {
    if (!resumeId || !analysis) {
      toast.err("暂无分析报告可导出");
      return;
    }
    setExporting(format);
    try {
      const token = getToken();
      const res = await fetch(
        `${API_BASE}/api/resume/${resumeId}/analyze/export?format=${format}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} }
      );
      if (!res.ok) {
        let detail = `导出失败 (${res.status})`;
        try {
          const j = await res.json();
          if (j.detail) detail = j.detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `resume_analysis_${resumeId}.${format === "pdf" ? "pdf" : "docx"}`;
      a.click();
      URL.revokeObjectURL(url);
      toast.ok(format === "pdf" ? "PDF 已下载" : "Word 已下载");
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "导出失败");
    } finally {
      setExporting(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[75] flex items-center justify-center bg-slate-900/45 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[min(88vh,800px)] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-sky-100 bg-white shadow-2xl shadow-sky-900/15"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sky-700">
              <IconSparkles className="h-4 w-4 shrink-0" />
              <span className="text-xs font-medium tracking-[0.14em]">RESUME ANALYSIS</span>
            </div>
            <h2 className="mt-1 truncate text-lg font-semibold tracking-tight text-slate-900">
              简历分析报告
            </h2>
            <p className="mt-0.5 truncate text-xs text-slate-400">{filename}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-sm text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          >
            关闭
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {loading && (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-sm text-slate-400">
              <div className="flex items-center gap-2">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </div>
              AI 正在阅读简历并撰写分析报告…
            </div>
          )}

          {!loading && analysis && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="sky">竞争力 {analysis.score}/10</Badge>
              </div>
              <section>
                <h3 className="text-sm font-semibold text-slate-900">总体评价</h3>
                <p className="mt-2 text-sm leading-7 text-slate-600">{analysis.summary}</p>
              </section>
              {SECTIONS.map(({ key, title }) => {
                const items = analysis[key];
                if (!Array.isArray(items) || items.length === 0) return null;
                return (
                  <section key={key}>
                    <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
                    <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-6 text-slate-600">
                      {(items as string[]).map((it) => (
                        <li key={it}>{it}</li>
                      ))}
                    </ul>
                  </section>
                );
              })}
            </div>
          )}

          {!loading && !analysis && (
            <div className="py-16 text-center text-sm text-slate-400">暂无分析内容</div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-100 bg-slate-50/80 px-5 py-3">
          <button type="button" className={btnCls("secondary", "sm")} onClick={onClose}>
            关闭
          </button>
          <button
            type="button"
            className={btnCls("secondary", "sm")}
            disabled={!analysis || !!exporting || !!loading}
            onClick={() => exportFile("docx")}
          >
            {exporting === "docx" ? "导出中…" : "导出 Word"}
          </button>
          <button
            type="button"
            className={btnCls("primary", "sm")}
            disabled={!analysis || !!exporting || !!loading}
            onClick={() => exportFile("pdf")}
          >
            {exporting === "pdf" ? "导出中…" : "导出 PDF"}
          </button>
        </div>
      </div>
    </div>
  );
}
