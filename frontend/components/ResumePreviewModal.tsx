"use client";

import { useEffect, useState } from "react";

import { API_BASE, getToken } from "@/lib/api";

async function readError(res: Response): Promise<string> {
  try {
    const j = await res.json();
    if (typeof j?.detail === "string") return j.detail;
    if (Array.isArray(j?.detail)) return j.detail.map((x: { msg?: string }) => x.msg).filter(Boolean).join("；");
  } catch {
    /* ignore */
  }
  if (res.status === 404) return "未找到预览文件，请重新上传简历后再试";
  return `加载失败 (${res.status})`;
}

export default function ResumePreviewModal({
  open,
  resumeId,
  filename,
  hasFile,
  onClose,
}: {
  open: boolean;
  resumeId: number | null;
  filename: string;
  hasFile: boolean;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<"pdf" | "text">("pdf");
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!open || resumeId == null) return;
    let revoked: string | null = null;
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError("");
      setPdfUrl(null);
      setText("");
      const token = getToken();
      const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};

      // 有文件标记时先拉 PDF；失败再回退文本
      if (hasFile) {
        try {
          const res = await fetch(`${API_BASE}/api/resume/${resumeId}/file`, { headers });
          if (!res.ok) throw new Error(await readError(res));
          const blob = await res.blob();
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          revoked = url;
          setPdfUrl(url);
          setMode("pdf");
          setLoading(false);
          return;
        } catch (e) {
          if (cancelled) return;
          setError(e instanceof Error ? e.message : "PDF 加载失败，已改为文本预览");
        }
      }

      try {
        const res = await fetch(`${API_BASE}/api/resume/${resumeId}/text-preview`, { headers });
        if (!res.ok) throw new Error(await readError(res));
        const data = await res.json();
        if (cancelled) return;
        setText(data.text || "（无文本内容）");
        setMode("text");
        if (!hasFile) {
          setError("当前简历没有保留 PDF 原件，仅显示提取文本。重新上传后可预览 PDF。");
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "预览失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [open, resumeId, hasFile]);

  if (!open || resumeId == null) return null;

  return (
    <div
      className="fixed inset-0 z-[75] flex items-center justify-center bg-slate-900/45 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex h-[min(88vh,860px)] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-sky-100 bg-white shadow-2xl shadow-sky-900/15"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0">
            <p className="text-xs font-medium tracking-[0.14em] text-sky-700">RESUME PREVIEW</p>
            <h2 className="mt-1 truncate text-lg font-semibold tracking-tight text-slate-900">
              {filename || "简历预览"}
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              {mode === "pdf" ? "PDF 原文预览" : "文本预览"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-slate-200 px-3.5 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-50 hover:text-slate-900"
          >
            关闭
          </button>
        </div>

        <div className="min-h-0 flex-1 bg-slate-50">
          {loading ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">加载中…</div>
          ) : mode === "pdf" && pdfUrl ? (
            <iframe title="简历 PDF 预览" src={pdfUrl} className="h-full w-full border-0" />
          ) : text ? (
            <div className="flex h-full flex-col">
              {error ? (
                <div className="border-b border-amber-100 bg-amber-50 px-5 py-2.5 text-xs text-amber-800">
                  {error}
                </div>
              ) : null}
              <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap px-5 py-4 text-sm leading-7 text-slate-700">
                {text}
              </pre>
            </div>
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
              <p className="text-sm font-medium text-red-600">{error || "无法预览"}</p>
              <p className="text-xs text-slate-400">可重新上传一份 PDF 后再点预览</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
