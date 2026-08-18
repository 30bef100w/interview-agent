"use client";

import { useEffect, useRef, useState } from "react";

import ResumeAnalysisModal, {
  type ResumeAnalysis,
} from "@/components/ResumeAnalysisModal";
import ResumePreviewModal from "@/components/ResumePreviewModal";
import { useToast } from "@/components/Toast";
import {
  Badge,
  ButtonLink,
  EmptyState,
  IconFile,
  IconUpload,
  btnCls,
} from "@/components/ui";
import { api } from "@/lib/api";

type Resume = {
  id: number;
  filename: string;
  profile: Record<string, unknown> | null;
  analysis?: ResumeAnalysis | null;
  has_file?: boolean;
  created_at: string;
};

const DEFAULT_KEY = "fa_default_resume_id";

export default function UploadPage() {
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [selected, setSelected] = useState<Resume | null>(null);
  const [parsing, setParsing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const [analysis, setAnalysis] = useState<ResumeAnalysis | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [profileText, setProfileText] = useState("");
  const [defaultId, setDefaultId] = useState<number | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(DEFAULT_KEY);
      if (raw) setDefaultId(Number(raw));
    } catch {
      /* ignore */
    }
    api<Resume[]>("/api/resume")
      .then((list) => {
        setResumes(list);
        if (list.length > 0) {
          const preferred =
            list.find((r) => String(r.id) === localStorage.getItem(DEFAULT_KEY)) ?? list[0];
          setSelected(preferred);
          setProfileText(preferred.profile ? JSON.stringify(preferred.profile, null, 2) : "");
          setAnalysis(preferred.analysis ?? null);
        }
      })
      .catch(() => window.location.assign("/login"));
  }, []);

  function setAsDefault(id: number) {
    setDefaultId(id);
    try {
      localStorage.setItem(DEFAULT_KEY, String(id));
    } catch {
      /* ignore */
    }
    toast.ok("已设为默认简历");
  }

  async function upload(file: File) {
    setUploading(true);
    setAnalysis(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const resume = await api<Resume>("/api/resume/upload", { method: "POST", body: form });
      setResumes((prev) => [resume, ...prev]);
      setSelected(resume);
      setProfileText("");
      toast.info("上传成功，AI 正在解析画像…");
      setParsing(true);
      const parsed = await api<{ profile: Record<string, unknown> }>(
        `/api/resume/${resume.id}/parse`,
        { method: "POST" }
      );
      setProfileText(JSON.stringify(parsed.profile, null, 2));
      setSelected((prev) => (prev ? { ...prev, profile: parsed.profile } : prev));
      setResumes((prev) =>
        prev.map((r) => (r.id === resume.id ? { ...r, profile: parsed.profile } : r))
      );
      toast.ok("画像解析完成，可检查后保存");
      if (!defaultId) setAsDefault(resume.id);
    } catch (err) {
      toast.err(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
      setParsing(false);
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) upload(file);
  }

  async function saveProfile() {
    if (!selected) return;
    setSaving(true);
    try {
      const profile = JSON.parse(profileText);
      const updated = await api<Resume>(`/api/resume/${selected.id}/profile`, {
        method: "PUT",
        body: JSON.stringify({ profile }),
      });
      setSelected(updated);
      setResumes((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      toast.ok("画像已保存");
    } catch (err) {
      toast.err(err instanceof Error ? err.message : "保存失败，请检查 JSON 格式");
    } finally {
      setSaving(false);
    }
  }

  async function removeResume() {
    if (!selected) return;
    if (!window.confirm(`确定删除「${selected.filename}」？`)) return;
    setDeleting(true);
    try {
      await api<null>(`/api/resume/${selected.id}`, { method: "DELETE" });
      const next = resumes.filter((r) => r.id !== selected.id);
      setResumes(next);
      if (defaultId === selected.id) {
        setDefaultId(null);
        localStorage.removeItem(DEFAULT_KEY);
      }
      const pick = next[0] ?? null;
      setSelected(pick);
      setProfileText(pick?.profile ? JSON.stringify(pick.profile, null, 2) : "");
      setAnalysis(pick?.analysis ?? null);
      setAnalysisOpen(false);
      toast.ok("简历已删除");
    } catch (err) {
      toast.err(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  }

  async function runAnalyze() {
    if (!selected) return;
    setAnalyzing(true);
    setAnalysis(null);
    setAnalysisOpen(true);
    try {
      const res = await api<{ analysis: ResumeAnalysis }>(`/api/resume/${selected.id}/analyze`, {
        method: "POST",
      });
      setAnalysis(res.analysis);
      setSelected((prev) => (prev ? { ...prev, analysis: res.analysis } : prev));
      setResumes((prev) =>
        prev.map((r) => (r.id === selected.id ? { ...r, analysis: res.analysis } : r))
      );
      toast.ok("分析完成");
    } catch (err) {
      toast.err(err instanceof Error ? err.message : "分析失败");
      setAnalysisOpen(false);
    } finally {
      setAnalyzing(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          我的简历
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          上传、管理与分析简历，作为面试官的提问依据
        </p>
      </div>

      <div
        onDrop={onDrop}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        className={`flex h-44 cursor-pointer flex-col items-center justify-center gap-2.5 rounded-2xl border-2 border-dashed text-center transition-all duration-150 ${
          dragging
            ? "scale-[1.01] border-sky-500 bg-sky-50/60 dark:bg-sky-950/40"
            : "border-zinc-300 hover:border-sky-400 hover:bg-sky-50/30 dark:border-zinc-700 dark:hover:border-sky-500 dark:hover:bg-sky-950/20"
        }`}
        onClick={() => fileInput.current?.click()}
      >
        <span
          className={`flex h-12 w-12 items-center justify-center rounded-2xl transition-colors ${
            dragging
              ? "bg-sky-600 text-white"
              : "bg-sky-100 text-sky-600 dark:bg-sky-950/60 dark:text-sky-400"
          }`}
        >
          <IconUpload className="h-6 w-6" />
        </span>
        <p className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
          {uploading ? "上传中…" : parsing ? "AI 解析画像中…" : "拖拽 PDF 到这里，或点击选择文件"}
        </p>
        <p className="text-xs text-zinc-400 dark:text-zinc-500">仅支持文字版 PDF</p>
        <input
          ref={fileInput}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload(file);
          }}
        />
      </div>

      {resumes.length === 0 && !uploading && (
        <EmptyState
          icon={<IconFile className="h-10 w-10" />}
          title="还没有简历"
          desc="上传一份文字版 PDF，AI 会抽取画像，之后就能开练"
          action={<ButtonLink href="/interview/new">已有简历？去开练</ButtonLink>}
        />
      )}

      {resumes.length > 0 && (
        <div>
          <h2 className="mb-2 text-sm font-medium text-zinc-600 dark:text-zinc-300">简历列表</h2>
          <div className="flex flex-wrap gap-2">
            {resumes.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => {
                  setSelected(r);
                  setProfileText(r.profile ? JSON.stringify(r.profile, null, 2) : "");
                  setAnalysis(r.analysis ?? null);
                }}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm transition-all ${
                  selected?.id === r.id
                    ? "border-sky-600 bg-sky-600 text-white shadow-sm shadow-sky-600/30"
                    : "border-zinc-200 bg-white text-zinc-600 hover:border-sky-300 hover:text-sky-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
                }`}
              >
                <IconFile className="h-3.5 w-3.5" />
                {r.filename}
                {defaultId === r.id && (
                  <span className={selected?.id === r.id ? "opacity-90" : "text-sky-600"}>·默认</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {selected && (
        <div className="flex flex-1 flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-medium text-zinc-600 dark:text-zinc-300">
              画像预览
              <span className="ml-2 text-xs text-zinc-400">可编辑，保存后作为面试上下文</span>
            </h2>
            <div className="flex flex-wrap items-center gap-2">
              {selected.profile && <Badge tone="emerald">已解析</Badge>}
              {defaultId === selected.id ? (
                <Badge tone="sky">默认简历</Badge>
              ) : (
                <button
                  type="button"
                  className={btnCls("ghost", "sm")}
                  onClick={() => setAsDefault(selected.id)}
                >
                  设为默认
                </button>
              )}
              <button
                type="button"
                className={btnCls("secondary", "md")}
                onClick={() => setPreviewOpen(true)}
              >
                <IconFile className="h-4 w-4" />
                预览简历
              </button>
              {analysis && (
                <button
                  type="button"
                  className={btnCls("ghost", "sm")}
                  onClick={() => setAnalysisOpen(true)}
                >
                  查看分析报告
                </button>
              )}
              <button
                type="button"
                className={btnCls("secondary", "sm")}
                disabled={analyzing || parsing}
                onClick={runAnalyze}
              >
                {analyzing ? "分析中…" : analysis ? "重新分析" : "AI 分析简历"}
              </button>
              <button
                type="button"
                className={btnCls("danger", "sm")}
                disabled={deleting}
                onClick={removeResume}
              >
                {deleting ? "删除中…" : "删除"}
              </button>
            </div>
          </div>
          <textarea
            value={profileText}
            onChange={(e) => setProfileText(e.target.value)}
            placeholder={parsing ? "解析中…" : "上传简历后在此显示画像"}
            spellCheck={false}
            className="min-h-[260px] flex-1 resize-y rounded-xl border border-zinc-200 bg-white p-4 font-mono text-sm text-zinc-900 outline-none transition-all focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
          />
          <div className="flex items-center justify-end">
            <button
              type="button"
              onClick={saveProfile}
              disabled={saving || parsing || !selected.profile}
              className={btnCls("primary")}
            >
              {saving ? "保存中…" : "保存画像"}
            </button>
          </div>
        </div>
      )}

      <ResumeAnalysisModal
        open={analysisOpen}
        resumeId={selected?.id ?? null}
        filename={selected?.filename ?? ""}
        analysis={analysis}
        loading={analyzing}
        onClose={() => setAnalysisOpen(false)}
      />
      <ResumePreviewModal
        open={previewOpen}
        resumeId={selected?.id ?? null}
        filename={selected?.filename ?? ""}
        hasFile={Boolean(selected?.has_file)}
        onClose={() => setPreviewOpen(false)}
      />
    </div>
  );
}
