"use client";

/** 多维度折线成长曲线（纯 SVG，无第三方图表库） */
export type GrowthSeries = {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
};

const COLORS = ["#0284c7", "#059669", "#7c3aed", "#ea580c", "#0f172a"];

export default function GrowthLineChart({
  labels,
  series,
  height = 220,
}: {
  labels: string[];
  series: GrowthSeries[];
  height?: number;
}) {
  const width = 640;
  const pad = { t: 16, r: 16, b: 36, l: 36 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const n = Math.max(labels.length, 1);
  const maxY = 10;
  const minY = 0;

  const xAt = (i: number) => pad.l + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const yAt = (v: number) => pad.t + innerH - ((v - minY) / (maxY - minY)) * innerH;

  function pathFor(values: (number | null)[]) {
    const parts: string[] = [];
    let started = false;
    values.forEach((v, i) => {
      if (v == null || Number.isNaN(v)) {
        started = false;
        return;
      }
      const cmd = started ? "L" : "M";
      parts.push(`${cmd}${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`);
      started = true;
    });
    return parts.join(" ");
  }

  return (
    <div className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="min-w-full">
        {[0, 2.5, 5, 7.5, 10].map((tick) => (
          <g key={tick}>
            <line
              x1={pad.l}
              x2={width - pad.r}
              y1={yAt(tick)}
              y2={yAt(tick)}
              className="stroke-slate-100"
              strokeWidth={1}
            />
            <text
              x={pad.l - 8}
              y={yAt(tick) + 3}
              textAnchor="end"
              className="fill-slate-400"
              fontSize={10}
            >
              {tick}
            </text>
          </g>
        ))}

        {series.map((s, idx) => (
          <g key={s.key}>
            <path
              d={pathFor(s.values)}
              fill="none"
              stroke={s.color || COLORS[idx % COLORS.length]}
              strokeWidth={2.2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {s.values.map((v, i) =>
              v == null ? null : (
                <circle
                  key={`${s.key}-${i}`}
                  cx={xAt(i)}
                  cy={yAt(v)}
                  r={3.2}
                  fill={s.color || COLORS[idx % COLORS.length]}
                />
              )
            )}
          </g>
        ))}

        {labels.map((lb, i) => (
          <text
            key={i}
            x={xAt(i)}
            y={height - 10}
            textAnchor="middle"
            className="fill-slate-400"
            fontSize={10}
          >
            {lb}
          </text>
        ))}
      </svg>
      <div className="mt-2 flex flex-wrap gap-3 px-1">
        {series.map((s, idx) => (
          <span key={s.key} className="inline-flex items-center gap-1.5 text-xs text-slate-500">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: s.color || COLORS[idx % COLORS.length] }}
            />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
