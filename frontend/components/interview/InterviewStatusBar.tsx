"use client";

import { Badge } from "@/components/ui";

type Props = {
  stage: string;
  roundsUsed: number;
  totalRounds: number;
  topicCount?: number;
  disconnected?: boolean;
  ttsAutoPlay: boolean;
  onToggleTts: () => void;
};

function stageLabel(stage: string) {
  const map: Record<string, { label: string; tone: "sky" | "emerald" | "amber" | "zinc" }> = {
    INTRO: { label: "自我介绍", tone: "sky" },
    ASKING: { label: "提问中", tone: "sky" },
    SUMMARIZING: { label: "正在汇总", tone: "amber" },
    FINISHED: { label: "已结束", tone: "zinc" },
  };
  return map[stage] ?? { label: stage, tone: "zinc" as const };
}

export default function InterviewStatusBar({
  stage,
  roundsUsed,
  totalRounds,
  topicCount,
  disconnected,
  ttsAutoPlay,
  onToggleTts,
}: Props) {
  const s = stageLabel(stage);
  const pct = totalRounds > 0 ? Math.min(100, Math.round((roundsUsed / totalRounds) * 100)) : 0;

  return (
    <div className="border-b border-zinc-200/80 bg-white/90 px-4 py-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/90">
      <div className="mx-auto flex max-w-2xl flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={s.tone}>{s.label}</Badge>
            <span className="text-xs text-zinc-500">
              第 {roundsUsed}/{totalRounds} 轮
              {topicCount ? ` · 题单 ${topicCount} 题` : ""}
            </span>
            {disconnected ? <Badge tone="amber">连接异常</Badge> : null}
          </div>
          <button
            type="button"
            onClick={onToggleTts}
            className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
              ttsAutoPlay
                ? "border-sky-200 bg-sky-50 text-sky-700"
                : "border-zinc-200 text-zinc-500 hover:border-zinc-300"
            }`}
          >
            题目播报 {ttsAutoPlay ? "开" : "关"}
          </button>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
          <div
            className="h-full rounded-full bg-gradient-to-r from-sky-500 to-emerald-500 transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    </div>
  );
}
