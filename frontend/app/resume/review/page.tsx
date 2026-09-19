"use client";

import { useCallback, useEffect, useState } from "react";

import ResumeReviewBoard, { type ResumeReview } from "@/components/ResumeReviewBoard";
import { useToast } from "@/components/Toast";
import {
  Badge,
  ButtonLink,
  EmptyState,
  IconFile,
  IconNotebook,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";

type Resume = {
  id: number;
  filename: string;
  profile: Record<string, unknown> | null;
  created_at: string;
};

const DEFAULT_KEY = "fa_default_resume_id";

export default function ResumeReviewPage() {
  const toast = useToast();
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [review, setReview] = useState<ResumeReview | null>(null);
  const [loading, setLoading] = useState(true);
  const [onlyWithNotes, setOnlyWithNotes] = useState(false);

  const loadReview = useCallback(async (resumeId: number) => {
    const data = await api<ResumeReview>(`/api/resume/${resumeId}/review`);
    setReview(data);
  }, []);

  useEffect(() => {
    api<Resume[]>("/api/resume")
      .then(async (list) => {
        setResumes(list);
        if (list.length === 0) {
          setSelectedId(null);
          setReview(null);
          return;
        }
        const stored = Number(localStorage.getItem(DEFAULT_KEY) || 0);
        const preferred = list.find((r) => r.id === stored) ?? list[0];
        setSelectedId(preferred.id);
        await loadReview(preferred.id);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          window.location.assign("/login");
          return;
        }
        toast.err(err instanceof Error ? err.message : "加载简历失败");
      })
      .finally(() => setLoading(false));
  }, [loadReview, toast]);

  async function selectResume(id: number) {
    setSelectedId(id);
    setReview(null);
    try {
      await loadReview(id);
    } catch (err) {
      toast.err(err instanceof Error ? err.message : "加载复盘失败");
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            简历复盘
          </h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            按实习 / 项目的 bullet 记下问答对和注释，方便针对性复习。与「我的简历」分开，互不影响。
          </p>
        </div>
        <ButtonLink href="/resume/upload" variant="ghost" size="sm">
          管理简历
        </ButtonLink>
      </div>

      {resumes.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {resumes.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => selectResume(r.id)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm transition-all ${
                selectedId === r.id
                  ? "border-sky-600 bg-sky-600 text-white shadow-sm shadow-sky-600/30"
                  : "border-zinc-200 bg-white text-zinc-600 hover:border-sky-300 hover:text-sky-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
              }`}
            >
              <IconFile className="h-3.5 w-3.5" />
              {r.filename}
            </button>
          ))}
          <label className="ml-auto inline-flex items-center gap-2 text-xs text-zinc-500">
            <input
              type="checkbox"
              checked={onlyWithNotes}
              onChange={(e) => setOnlyWithNotes(e.target.checked)}
            />
            只看已有笔记
          </label>
        </div>
      )}

      {loading ? (
        <p className="py-16 text-center text-sm text-zinc-400">加载中…</p>
      ) : resumes.length === 0 ? (
        <EmptyState
          icon={<IconNotebook className="h-10 w-10" />}
          title="还没有简历"
          desc="先在「我的简历」上传并解析画像，再回来按 bullet 记问答和注释"
          action={<ButtonLink href="/resume/upload">去上传简历</ButtonLink>}
        />
      ) : !review ? (
        <p className="py-16 text-center text-sm text-zinc-400">加载复盘失败，请重选一份简历</p>
      ) : !review.has_profile ? (
        <EmptyState
          icon={<IconFile className="h-10 w-10" />}
          title="这份简历还没有结构化画像"
          desc="到「我的简历」里完成解析后，实习和项目才会按 bullet 展开"
          action={<ButtonLink href="/resume/upload">去解析画像</ButtonLink>}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-400">
            {review.has_profile && <Badge tone="emerald">已解析</Badge>}
            <span>点击一条经历下的 bullet 展开，可添加问答对或注释</span>
          </div>
          <ResumeReviewBoard
            review={review}
            onlyWithNotes={onlyWithNotes}
            onChanged={() => (selectedId ? loadReview(selectedId) : Promise.resolve())}
          />
        </>
      )}
    </div>
  );
}
