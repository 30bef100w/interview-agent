"use client";

import { useEffect, useState } from "react";

import { useToast } from "@/components/Toast";
import { btnCls } from "@/components/ui";
import { api } from "@/lib/api";
import {
  CONTACT_EMAIL,
  FEEDBACK_CATEGORIES,
  GITHUB_LABEL,
  GITHUB_URL,
} from "@/lib/contact";

export type FeedbackModalMode = "contact" | "second_session";

type Props = {
  mode: FeedbackModalMode;
  open: boolean;
  onClose: () => void;
  onSubmitted?: () => void;
};

export default function FeedbackModal({ mode, open, onClose, onSubmitted }: Props) {
  const toast = useToast();
  const [category, setCategory] = useState("ux");
  const [content, setContent] = useState("");
  const [contact, setContact] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setCategory("ux");
    setContent("");
    setContact("");
    setSubmitting(false);
  }, [open, mode]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose, submitting]);

  async function submit() {
    const text = content.trim();
    if (text.length < 2) {
      toast.err("请至少写几句意见");
      return;
    }
    setSubmitting(true);
    try {
      await api("/api/feedback", {
        method: "POST",
        body: JSON.stringify({
          source: mode,
          category,
          content: text,
          contact: mode === "contact" ? contact.trim() : "",
          page_url: typeof window !== "undefined" ? window.location.pathname : "",
        }),
      });
      toast.ok("感谢反馈，我们已收到");
      onSubmitted?.();
      onClose();
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

  const isContact = mode === "contact";

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-modal-title"
        className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-sky-100 bg-white shadow-2xl shadow-sky-900/10"
      >
        <div className="border-b border-sky-50 px-6 py-5">
          <p className="text-xs font-medium tracking-[0.16em] text-sky-700">
            {isContact ? "CONTACT" : "FEEDBACK"}
          </p>
          <h2 id="feedback-modal-title" className="mt-1 text-xl font-semibold text-slate-900">
            {isContact ? "意见反馈" : "愿意给我们一点意见吗？"}
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            {isContact
              ? "内测阶段欢迎直接留言，也可以通过下方方式找到我。"
              : "你已完成 2 场模拟面试，花 1 分钟说说感受，会帮我们做得更好。"}
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {isContact ? (
            <div className="mb-5 rounded-xl border border-sky-100 bg-sky-50/50 px-4 py-3 text-sm text-slate-700">
              <div className="font-medium text-slate-900">联系方式</div>
              <ul className="mt-2 space-y-2">
                <li>
                  <span className="text-slate-500">邮箱：</span>
                  <a
                    href={`mailto:${CONTACT_EMAIL}`}
                    className="font-medium text-sky-700 hover:underline"
                  >
                    {CONTACT_EMAIL}
                  </a>
                </li>
                <li>
                  <span className="text-slate-500">GitHub：</span>
                  <a
                    href={GITHUB_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-sky-700 hover:underline"
                  >
                    {GITHUB_LABEL}
                  </a>
                </li>
              </ul>
            </div>
          ) : null}

          <div className="space-y-4">
            <label className="block">
              <span className="text-sm font-medium text-slate-800">反馈类型</span>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20"
              >
                {FEEDBACK_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="text-sm font-medium text-slate-800">
                意见内容 <span className="text-red-500">*</span>
              </span>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={5}
                maxLength={4000}
                placeholder={
                  isContact
                    ? "描述你遇到的问题或建议，越具体越好…"
                    : "整体体验如何？哪里好用、哪里想改进？"
                }
                className="mt-1.5 w-full resize-y rounded-xl border border-slate-200 px-3 py-2.5 text-sm leading-6 text-slate-800 outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20"
              />
            </label>

            {isContact ? (
              <label className="block">
                <span className="text-sm font-medium text-slate-800">你的联系方式（选填）</span>
                <input
                  type="text"
                  value={contact}
                  onChange={(e) => setContact(e.target.value)}
                  maxLength={256}
                  placeholder="微信 / 邮箱，方便回访"
                  className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm text-slate-800 outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20"
                />
              </label>
            ) : null}
          </div>
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-sky-50 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className={btnCls("secondary")}
          >
            {isContact ? "取消" : "稍后再说"}
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className={btnCls("primary")}
          >
            {submitting ? "提交中…" : "提交反馈"}
          </button>
        </div>
      </div>
    </div>
  );
}
