"use client";

/** 多维度折线成长曲线（纯 SVG，无第三方图表库） */
export type GrowthSeries = {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
};

const COLORS = ["#0284c7", "#059669", "#7c3aed", "#ea580c", "#0f172a"];

function pickLabelIndexes(n: number, maxTicks: number): number[] {
  if (n <= 0) return [];
  if (n <= maxTicks) return Array.from({ length: n }, (_, i) => i);
  const idxs: number[] = [];
  for (let t = 0; t < maxTicks; t++) {
    idxs.push(Math.round((t * (n - 1)) / (maxTicks - 1)));
  }
  return [...new Set(idxs)];
}

function pickDateTickIndexes(labels: string[], maxTicks: number): number[] {
  const n = labels.length;
  if (n <= maxTicks) return Array.from({ length: n }, (_, i) => i);
  const out: number[] = [];
  const used = new Set<string>();
  for (const i of pickLabelIndexes(n, maxTicks)) {
    const day = labels[i] || "";
    if (used.has(day)) continue;
    used.add(day);
    out.push(i);
  }
  if (n > 0 && !out.includes(0)) {
    out.unshift(0);
    used.add(labels[0] || "");
  }
  if (n > 0 && !out.includes(n - 1)) {
    const last = labels[n - 1] || "";
    if (!used.has(last)) out.push(n - 1);
  }
  return [...new Set(out)].sort((a, b) => a - b);
}

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
  const n = Math.max(labels.length, 1);
  const crowded = n > 10;
  const pad = { t: 16, r: 16, b: crowded ? 44 : 36, l: 36 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const maxTicks = Math.max(4, Math.min(8, Math.floor(innerW / 56)));
  const labelIdx = new Set(pickDateTickIndexes(labels, maxTicks));
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
                >
                  <title>{`第 ${i + 1} 场${labels[i] ? ` · ${labels[i]}` : ""} · ${s.label} ${v}`}</title>
                </circle>
              )
            )}
          </g>
        ))}

        {labels.map((lb, i) =>
          labelIdx.has(i) ? (
            <text
              key={i}
              x={xAt(i)}
              y={height - 12}
              textAnchor={crowded && i === 0 ? "start" : crowded && i === n - 1 ? "end" : "middle"}
              className="fill-slate-400"
              fontSize={10}
            >
              {lb}
            </text>
          ) : null
        )}
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
