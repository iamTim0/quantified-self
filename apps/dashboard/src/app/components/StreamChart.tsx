"use client";

import { useMemo, useState } from "react";
import { useI18n } from "../lib/i18n/provider";
import { describeMetric } from "../lib/metrics/catalog";
import type { StreamPoint } from "./WorkoutDetail";

/**
 * One series inside a workout, with the range each point stands on.
 *
 * **The band is the reason this is not a plain line.** Every point here is a
 * bucket — the server decimates in SQL so a three-hour ride costs the same as a
 * twenty-minute run — and a bucket's mean hides its extremes. A minute averaging
 * 162 bpm says nothing about whether the pulse was flat or ran from 140 to 186,
 * and those are different workouts. So the mean is the line and the bucket's
 * min/max is a band behind it: the shape a reader would have seen at full
 * resolution, without transferring it.
 *
 * Hand-rolled SVG rather than Chart.js, the way `AnalysisTab` draws its heatmap
 * and sparkline. A band plus a line is two paths; the library would be loaded to
 * produce the same two.
 *
 * **Colour.** One series, so one hue and no legend — the heading names it
 * (dataviz: a legend for two or more). Values and labels wear text tokens, never
 * the series colour.
 *
 * Every colour here is a CSS variable rather than a hex literal, which is what
 * makes this chart follow the theme at all. The `[data-theme="dark"]` block in
 * `globals.css` rewrites Tailwind *utility classes*; a hex in a `stroke`
 * attribute is not a class, so the grid used to draw a light-theme `#e2e8f0` on
 * a dark card. An SVG presentation attribute resolves `var()` directly, so this
 * needs no JavaScript — unlike the canvas charts, which need `useChartTheme`.
 */

const SERIES = "var(--chart-series)";
const BAND = "var(--chart-series-band)";
/* `--muted-foreground` (#64748b, 4.71:1 on white), not the slate-400 this held
   before: #94a3b8 is 2.56:1 and these are axis labels, which are text. */
const INK_MUTED = "var(--muted-foreground)";
const GRID = "var(--border)";
const HALO = "var(--card)";

const WIDTH = 760;
const HEIGHT = 200;
const PAD = { top: 16, right: 16, bottom: 24, left: 40 };

interface Props {
  metricType: string;
  unit: string;
  bucketSeconds: number;
  points: StreamPoint[];
  truncated: boolean;
}

export default function StreamChart({
  metricType,
  unit,
  bucketSeconds,
  points,
  truncated,
}: Props) {
  const { t, locale, formatNumber, formatDateTime } = useI18n();
  const [hover, setHover] = useState<number | null>(null);
  const described = describeMetric(metricType, locale);

  const plot = useMemo(() => {
    const usable = points.filter((point) => point.avg !== null);
    if (usable.length < 2) return null;

    const times = usable.map((point) => new Date(point.t).getTime());
    const lows = usable.map((point) => point.min ?? point.avg ?? 0);
    const highs = usable.map((point) => point.max ?? point.avg ?? 0);
    const minT = Math.min(...times);
    const maxT = Math.max(...times);
    const minV = Math.min(...lows);
    const maxV = Math.max(...highs);
    const spanT = maxT - minT || 1;
    // A flat series still needs a band to sit in rather than collapsing onto the axis.
    const spanV = maxV - minV || 1;

    const innerW = WIDTH - PAD.left - PAD.right;
    const innerH = HEIGHT - PAD.top - PAD.bottom;
    const x = (time: number) => PAD.left + ((time - minT) / spanT) * innerW;
    const y = (value: number) => PAD.top + innerH - ((value - minV) / spanV) * innerH;

    const line = usable
      .map((point, index) => `${index === 0 ? "M" : "L"} ${x(times[index]).toFixed(1)} ${y(point.avg as number).toFixed(1)}`)
      .join(" ");

    const upper = usable.map((point, index) => `${x(times[index]).toFixed(1)},${y(highs[index]).toFixed(1)}`);
    const lower = usable
      .map((point, index) => `${x(times[index]).toFixed(1)},${y(lows[index]).toFixed(1)}`)
      .reverse();
    const band = `M ${upper.join(" L ")} L ${lower.join(" L ")} Z`;

    return { usable, times, x, y, line, band, minV, maxV, innerH };
  }, [points]);

  if (!plot) return null;

  const active = hover === null ? null : plot.usable[hover];

  return (
    <figure className="glass-card space-y-2 rounded-2xl border border-line bg-surface p-4 shadow-sm">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-bold text-ink">
          {described.label}
          {unit && <span className="ml-1 text-xs font-semibold text-ink-muted">{unit}</span>}
        </span>
        <span className="text-[11px] text-ink-muted">
          {t("workouts.streamBucket", { seconds: bucketSeconds })} ·{" "}
          {t("workouts.streamRange", {
            min: formatNumber(plot.minV, { maximumFractionDigits: described.precision }),
            max: formatNumber(plot.maxV, { maximumFractionDigits: described.precision }),
          })}
        </span>
      </figcaption>

      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-[200px] w-full min-w-[420px]"
          role="img"
          aria-label={`${described.label} ${unit}`}
          onMouseLeave={() => setHover(null)}
        >
          {/* Recessive grid: two rules, no box, no ticks a reader has to decode. */}
          {[0, 0.5, 1].map((fraction) => {
            const value = plot.minV + (plot.maxV - plot.minV) * (1 - fraction);
            const yy = PAD.top + plot.innerH * fraction;
            return (
              <g key={fraction}>
                <line
                  x1={PAD.left}
                  x2={WIDTH - PAD.right}
                  y1={yy}
                  y2={yy}
                  stroke={GRID}
                  strokeWidth={1}
                />
                <text x={4} y={yy + 3} fontSize={10} fill={INK_MUTED}>
                  {formatNumber(value, { maximumFractionDigits: 0 })}
                </text>
              </g>
            );
          })}

          {/* The range each bucket stands on, behind the mean. */}
          <path d={plot.band} fill={BAND} stroke="none" />
          <path d={plot.line} fill="none" stroke={SERIES} strokeWidth={2} strokeLinejoin="round" />

          {active && hover !== null && (
            <g>
              <line
                x1={plot.x(plot.times[hover])}
                x2={plot.x(plot.times[hover])}
                y1={PAD.top}
                y2={PAD.top + plot.innerH}
                stroke={INK_MUTED}
                strokeWidth={1}
                strokeDasharray="3 3"
              />
              <circle
                cx={plot.x(plot.times[hover])}
                cy={plot.y(active.avg as number)}
                r={4}
                fill={SERIES}
                stroke={HALO}
                strokeWidth={2}
              />
            </g>
          )}

          {/* One transparent column per bucket: a hit target bigger than the mark. */}
          {plot.usable.map((point, index) => {
            const step = (WIDTH - PAD.left - PAD.right) / Math.max(plot.usable.length - 1, 1);
            return (
              <rect
                key={point.t}
                x={plot.x(plot.times[index]) - step / 2}
                y={PAD.top}
                width={Math.max(step, 6)}
                height={plot.innerH}
                fill="transparent"
                onMouseEnter={() => setHover(index)}
              />
            );
          })}
        </svg>
      </div>

      <div className="flex min-h-4 flex-wrap justify-between gap-2 text-[11px] text-ink-muted">
        <span>
          {active
            ? `${formatDateTime(active.t)} · ${formatNumber(active.avg as number, {
                maximumFractionDigits: described.precision,
              })} ${unit}${
                active.min !== null && active.max !== null && active.min !== active.max
                  ? ` (${formatNumber(active.min, { maximumFractionDigits: 0 })}–${formatNumber(
                      active.max,
                      { maximumFractionDigits: 0 },
                    )})`
                  : ""
              }`
            : ""}
        </span>
        {truncated && <span className="text-warn-ink">{t("workouts.streamTruncated")}</span>}
      </div>
    </figure>
  );
}
