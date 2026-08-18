"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { btnCls } from "@/components/ui";

const KEY = "fa_onboarding_done";

const STEPS = [
  {
    title: "上传简历",
    desc: "支持文字版 PDF，AI 会抽取技术栈与项目画像。",
    href: "/resume/upload",
    cta: "去上传",
  },
  {
    title: "开始模拟面试",
    desc: "选全流程或专项，设置轮次，进入真实技术面节奏。",
    href: "/interview/new",
    cta: "去开练",
  },
  {
    title: "查看报告复盘",
    desc: "逐题评分、雷达图与建议，支持导出 Word / PDF。",
    href: "/history",
    cta: "看记录",
  },
];

export default function OnboardingModal() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try {
      if (!localStorage.getItem(KEY)) setOpen(true);
    } catch {
      /* ignore */
    }
  }, []);

  function dismiss() {
    try {
      localStorage.setItem(KEY, "1");
    } catch {
      /* ignore */
    }
    setOpen(false);
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-sky-100 bg-white p-6 shadow-2xl shadow-sky-900/10">
        <p className="text-xs font-medium tracking-[0.18em] text-sky-700">欢迎使用</p>
        <h2 className="mt-2 text-xl font-semibold tracking-tight text-slate-900">
          三步开始你的第一场模拟面试
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">
          先准备好简历，再开练，最后用报告查漏补缺。
        </p>
        <ol className="mt-6 space-y-3">
          {STEPS.map((s, i) => (
            <li
              key={s.title}
              className="flex items-start gap-3 rounded-xl border border-slate-100 bg-slate-50/80 px-4 py-3"
            >
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-600 text-xs font-semibold text-white">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-slate-900">{s.title}</div>
                <p className="mt-0.5 text-xs leading-5 text-slate-500">{s.desc}</p>
              </div>
              <Link href={s.href} onClick={dismiss} className={btnCls("ghost", "sm")}>
                {s.cta}
              </Link>
            </li>
          ))}
        </ol>
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <button type="button" onClick={dismiss} className={btnCls("secondary")}>
            稍后再说
          </button>
          <Link href="/resume/upload" onClick={dismiss} className={btnCls("primary")}>
            从上传简历开始
          </Link>
        </div>
      </div>
    </div>
  );
}
