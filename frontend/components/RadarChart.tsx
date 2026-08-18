"use client";

import { useState } from "react";

export type RadarDatum = { label: string; value: number };

const MAX = 10;
const RINGS = [2, 4, 6, 8, 10];

/** 纯 SVG 雷达图：支持维度悬浮高亮与数值提示。 */
export default function RadarChart({
  data,
  size = 320,
}: {
  data: RadarDatum[];
  size?: number;
}) {
  const [active, setActive] = useState<number | null>(null);
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 44;
  const n = Math.max(data.length, 1);

  const angle = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const point = (i: number, radius: number) => ({
    x: cx + radius * Math.cos(angle(i)),
    y: cy + radius * Math.sin(angle(i)),
  });
  const poly = (radius: number) =>
    data
      .map((_, i) => {
        const p = point(i, radius);
        return `${p.x},${p.y}`;
      })
      .join(" ");

  const valuePoints = data.map((d, i) =>
    point(i, (Math.min(Math.max(d.value, 0), MAX) / MAX) * r)
  );

  const tip = active !== null ? data[active] : null;
  const tipPos = active !== null ? valuePoints[active] : null;

  return (
    <div className="relative mx-auto w-full max-w-[340px]">
      <svg
        viewBox={`0 0 ${size} ${size}`}
        className="w-full"
        onMouseLeave={() => setActive(null)}
      >
        {RINGS.map((ring) => (
          <polygon
            key={ring}
            points={poly((ring / MAX) * r)}
            className="fill-none stroke-sky-100"
            strokeWidth={ring === MAX ? 1.5 : 1}
          />
        ))}
        {data.map((_, i) => {
          const p = point(i, r);
          return (
            <line
              key={i}
              x1={cx}
              y1={cy}
              x2={p.x}
              y2={p.y}
              className={active === i ? "stroke-sky-300" : "stroke-sky-100"}
              strokeWidth={active === i ? 1.6 : 1}
            />
          );
        })}
        <polygon
          points={valuePoints.map((p) => `${p.x},${p.y}`).join(" ")}
          className="fill-sky-500/15 stroke-sky-500"
          strokeWidth={2}
          strokeLinejoin="round"
        />
        {valuePoints.map((p, i) => (
          <g key={i} onMouseEnter={() => setActive(i)} className="cursor-pointer">
            <circle cx={p.x} cy={p.y} r={14} className="fill-transparent" />
            <circle
              cx={p.x}
              cy={p.y}
              r={active === i ? 5.5 : 3.5}
              className={active === i ? "fill-sky-600" : "fill-sky-500"}
            />
          </g>
        ))}
        {data.map((d, i) => {
          const p = point(i, r + 24);
          const on = active === i;
          return (
            <text
              key={d.label}
              x={p.x}
              y={p.y}
              textAnchor="middle"
              dominantBaseline="middle"
              onMouseEnter={() => setActive(i)}
              className={`cursor-pointer text-[11px] ${
                on ? "fill-sky-700 font-semibold" : "fill-slate-500"
              }`}
            >
              {d.label}
            </text>
          );
        })}
      </svg>

      {tip && tipPos && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[120%] rounded-xl border border-sky-100 bg-white px-3 py-2 text-xs shadow-lg shadow-sky-900/10"
          style={{
            left: `${(tipPos.x / size) * 100}%`,
            top: `${(tipPos.y / size) * 100}%`,
          }}
        >
          <div className="font-medium text-slate-800">{tip.label}</div>
          <div className="mt-0.5 text-sky-700">
            {Number(tip.value).toFixed(1)}
            <span className="text-slate-400"> / 10</span>
          </div>
        </div>
      )}
    </div>
  );
}
