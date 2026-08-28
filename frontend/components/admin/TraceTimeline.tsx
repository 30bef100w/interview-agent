"use client";

export type TimelineEvent = {
  kind: string;
  ts?: string;
  node?: string;
  duration_ms?: number | null;
  outcome?: string;
  detail?: Record<string, unknown>;
};

export type TracePayload = {
  session_id: number;
  timeline?: TimelineEvent[];
  engine_trace?: unknown[];
  create_trace?: unknown;
  guard_events?: unknown[];
};

const KIND_LABEL: Record<string, string> = {
  create: "规划",
  engine: "引擎",
  guard: "门禁",
};

const KIND_COLOR: Record<string, string> = {
  create: "border-sky-700/50 bg-sky-950/40 text-sky-300",
  engine: "border-emerald-700/50 bg-emerald-950/40 text-emerald-300",
  guard: "border-amber-700/50 bg-amber-950/40 text-amber-300",
};

export function TraceTimeline({
  trace,
  showRaw,
  onToggleRaw,
}: {
  trace: TracePayload;
  showRaw?: boolean;
  onToggleRaw?: () => void;
}) {
  const timeline = trace.timeline ?? [];

  return (
    <>
      <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-4 text-xs text-zinc-500">
            <span>事件 {timeline.length} 条</span>
            <span>引擎 {trace.engine_trace?.length ?? 0}</span>
            <span>门禁 {trace.guard_events?.length ?? 0}</span>
          </div>
          {onToggleRaw ? (
            <button
              type="button"
              onClick={onToggleRaw}
              className="text-xs text-zinc-500 hover:text-zinc-300"
            >
              {showRaw ? "隐藏原始 JSON" : "查看原始 JSON"}
            </button>
          ) : null}
        </div>
        {timeline.length === 0 ? (
          <p className="text-sm text-zinc-500">暂无 trace 事件（完成一场面试后可见）</p>
        ) : (
          <ol className="relative space-y-0 border-l border-zinc-700 pl-4">
            {timeline.map((ev, i) => {
              const kind = ev.kind || "engine";
              const chip = KIND_COLOR[kind] || KIND_COLOR.engine;
              return (
                <li key={`${ev.ts}-${ev.node}-${i}`} className="relative pb-5">
                  <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-zinc-600 ring-4 ring-zinc-950" />
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${chip}`}>
                      {KIND_LABEL[kind] || kind}
                    </span>
                    <span className="text-sm font-medium text-zinc-200">{ev.node}</span>
                    {typeof ev.duration_ms === "number" ? (
                      <span className="text-xs text-zinc-500">{ev.duration_ms} ms</span>
                    ) : null}
                    {ev.outcome ? (
                      <span
                        className={`text-xs ${
                          ev.outcome === "error" ? "text-red-400" : "text-zinc-500"
                        }`}
                      >
                        {ev.outcome}
                      </span>
                    ) : null}
                  </div>
                  {ev.ts ? <div className="mt-0.5 text-[11px] text-zinc-600">{ev.ts}</div> : null}
                  {ev.detail && Object.keys(ev.detail).length > 0 ? (
                    <pre className="mt-2 max-h-32 overflow-auto rounded-lg bg-zinc-900 p-2 text-[11px] text-zinc-400">
                      {JSON.stringify(ev.detail, null, 2)}
                    </pre>
                  ) : null}
                </li>
              );
            })}
          </ol>
        )}
      </div>

      {showRaw ? (
        <pre className="max-h-[50vh] overflow-auto rounded-xl border border-zinc-800 bg-zinc-950 p-4 text-xs leading-relaxed text-zinc-300">
          {JSON.stringify(trace, null, 2)}
        </pre>
      ) : null}
    </>
  );
}
