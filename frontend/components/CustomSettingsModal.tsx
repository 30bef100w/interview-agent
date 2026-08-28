"use client";

import { useEffect } from "react";

import { IconSliders } from "@/components/ui";

export type DedupScope = "none" | "last5" | "last10" | "all";

export type CustomSettings = {
  count: number;
  practiceFocus: string;
  skipCoding: boolean;
  dedupScope: DedupScope;
  reviewMode: boolean;
};

const DEDUP_OPTIONS: { value: DedupScope; label: string; desc: string }[] = [
  { value: "all", label: "永久去重（全部历史）", desc: "默认：与全部历史场次问法去重，换句重复也拦" },
  { value: "last10", label: "近 10 场不重复问法", desc: "同知识点可再考，避开近 10 场已问过的问法" },
  { value: "last5", label: "近 5 场不重复问法", desc: "同知识点可再考，避开近 5 场已问过的问法" },
  { value: "none", label: "允许重复", desc: "不限制与历史问法撞车" },
];

export function countActiveCustom(s: CustomSettings, mode: string): number {
  let n = 0;
  if (s.count !== 8) n += 1;
  if (s.practiceFocus.trim()) n += 1;
  if (s.skipCoding && mode === "full") n += 1;
  if (s.dedupScope !== "all") n += 1;
  if (s.reviewMode) n += 1;
  return n;
}

export default function CustomSettingsModal({
  open,
  value,
  mode,
  onChange,
  onClose,
}: {
  open: boolean;
  value: CustomSettings;
  mode: "full" | "specialized";
  onChange: (next: CustomSettings) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  function patch(partial: Partial<CustomSettings>) {
    onChange({ ...value, ...partial });
  }

  return (
    <div
      className="fixed inset-0 z-[75] flex items-center justify-center bg-slate-900/45 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[min(88vh,720px)] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-sky-100 bg-white shadow-2xl shadow-sky-900/15"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sky-700">
              <IconSliders className="h-4 w-4 shrink-0" />
              <span className="text-xs font-medium tracking-[0.14em]">CUSTOM</span>
            </div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight text-slate-900">自定义设置</h2>
            <p className="mt-0.5 text-xs text-slate-400">进阶选项，默认即可开练；改完点完成即可。</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-sm text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          >
            关闭
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5">
          <section>
            <div className="mb-2 flex items-center justify-between">
              <label className="text-sm font-medium text-slate-800">总轮次上限</label>
              <span className="rounded-full bg-sky-50 px-2.5 py-0.5 text-sm font-semibold text-sky-600">
                {value.count} 轮
              </span>
            </div>
            <input
              type="range"
              min={4}
              max={20}
              value={value.count}
              onChange={(e) => patch({ count: Number(e.target.value) })}
              className="w-full accent-sky-600"
            />
            <div className="mt-1 flex justify-between text-[11px] text-slate-400">
              <span>4 · 快速</span>
              <span>含追问，主问题约 60-70%</span>
              <span>20 · 深度</span>
            </div>
          </section>

          <section>
            <label className="mb-2 block text-sm font-medium text-slate-800">
              本场练习焦点 <span className="font-normal text-slate-400">（可选，仅本场）</span>
            </label>
            <textarea
              value={value.practiceFocus}
              onChange={(e) => patch({ practiceFocus: e.target.value.slice(0, 500) })}
              rows={3}
              placeholder="例如：缓存一致性、高并发读链路；与岗位 JD 一样只用于题库加权召回"
              className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20"
            />
            <p className="mt-1.5 text-[11px] leading-4 text-slate-400">
              不会整段写入规划 Prompt；开练页粘贴 JD 时与此合并加权。
            </p>
          </section>

          <section>
            <label className="mb-2 block text-sm font-medium text-slate-800">环节与模式</label>
            <div className="space-y-2">
              <label
                className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 transition ${
                  mode !== "full"
                    ? "cursor-not-allowed border-slate-100 bg-slate-50 opacity-50"
                    : value.skipCoding
                      ? "border-sky-400 bg-sky-50/60"
                      : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <input
                  type="checkbox"
                  className="mt-0.5 accent-sky-600"
                  checked={value.skipCoding}
                  disabled={mode !== "full"}
                  onChange={(e) => patch({ skipCoding: e.target.checked })}
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-slate-900">去掉算法环节</span>
                  <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                    {mode === "full"
                      ? "全流程中不插入编码题，只保留项目 / 八股 / HR"
                      : "仅全流程混合面可用"}
                  </span>
                </span>
              </label>

              <label
                className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 transition ${
                  value.reviewMode
                    ? "border-sky-400 bg-sky-50/60"
                    : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <input
                  type="checkbox"
                  className="mt-0.5 accent-sky-600"
                  checked={value.reviewMode}
                  onChange={(e) => patch({ reviewMode: e.target.checked })}
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-slate-900">复习模式</span>
                  <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                    根据成长档案短板优先复盘薄弱主题（有历史报告时生效）
                  </span>
                </span>
              </label>
            </div>
          </section>

          <section>
            <label className="mb-2 block text-sm font-medium text-slate-800">题目去重</label>
            <div className="grid gap-2">
              {DEDUP_OPTIONS.map((opt) => {
                const selected = value.dedupScope === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => patch({ dedupScope: opt.value })}
                    className={`rounded-xl border px-3.5 py-3 text-left transition ${
                      selected
                        ? "border-sky-400 bg-sky-50/60 ring-2 ring-sky-500/15"
                        : "border-slate-200 hover:border-slate-300"
                    }`}
                  >
                    <div className="text-sm font-medium text-slate-900">{opt.label}</div>
                    <div className="mt-0.5 text-xs text-slate-500">{opt.desc}</div>
                  </button>
                );
              })}
            </div>
          </section>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-100 px-5 py-3.5">
          <button
            type="button"
            onClick={() =>
              onChange({
                count: 8,
                practiceFocus: "",
                skipCoding: false,
                dedupScope: "all",
                reviewMode: false,
              })
            }
            className="rounded-xl px-3 py-2 text-sm text-slate-500 hover:bg-slate-50 hover:text-slate-800"
          >
            恢复默认
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-500"
          >
            完成
          </button>
        </div>
      </div>
    </div>
  );
}
