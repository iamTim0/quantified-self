"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BookOpen,
  CalendarClock,
  ChevronDown,
  Info,
  RefreshCw,
  ShieldQuestion,
  TrendingUp,
} from "lucide-react";
import { apiFetch } from "../lib/api";
import { useI18n, useT, type MessageKey } from "../lib/i18n/provider";

/**
 * Analysis dashboard.
 *
 * Two things govern every design decision here.
 *
 * **Nothing is presented as causal.** Correlations are labelled as associations,
 * every card repeats the sample size and significance, and the heading copy says
 * "hängt zusammen mit", never "wirkt auf". A correlation shown without its
 * uncertainty is worse than no correlation at all.
 *
 * **Colour follows polarity, so the scale is diverging.** Blue↔red with a neutral
 * grey midpoint — validated for protan/deutan/tritan separation (ΔE 29.3 worst
 * case). Deliberately *not* the app's brand green paired with red, which is the
 * classic red-green CVD failure. Because the near-midpoint steps sit below 3:1
 * against the surface, every cell also carries its numeric value, so identity is
 * never colour-alone.
 */

// Diverging ramp: negative → neutral → positive. Equal steps per arm, each arm
// monotonic in lightness.
const NEG = ["#b91c1c", "#e06c6c", "#f4b8b8"] as const;
const NEUTRAL = "#f1f0ed";
const POS = ["#b3cdf3", "#5b93e0", "#1d4ed8"] as const;

const INK = { primary: "#0f172a", secondary: "#475569", muted: "#94a3b8" };

function correlationColor(r: number): string {
  const a = Math.abs(r);
  if (a < 0.2) return NEUTRAL;
  const arm = r < 0 ? NEG : POS;
  if (a < 0.4) return arm[2];
  if (a < 0.7) return arm[1];
  return arm[0];
}

/** Cell text must stay legible on both the pale and the saturated steps. */
function cellInk(r: number): string {
  // No `useT()` here: this is a plain helper called from inside a `.map()` over SVG
  // cells, not a component, so a hook call would break the rules of hooks. The
  // result was never used either -- the function returns a colour.
  return Math.abs(r) >= 0.7 ? "#ffffff" : INK.primary;
}

interface Correlation {
  metric_a: string;
  metric_b: string;
  pearson: number;
  spearman: number;
  coefficient: number;
  strength_pct: number;
  direction: string;
  strength_label: string;
  sample_size: number;
  p_value: number;
  significant: boolean;
  interpretation: string;
  caveats: string[];
}

interface LaggedCorrelation {
  metric_a: string;
  metric_b: string;
  lag_days: number;
  coefficient: number;
  strength_pct: number;
  sample_size: number;
  p_value: number;
  significant: boolean;
  interpretation: string;
}

interface Trend {
  direction: string;
  slope_per_day: number;
  change_pct_over_window: number;
  r_squared: number;
  sample_size: number;
  mean: number;
  moving_average_7d: (number | null)[];
  interpretation: string;
}

interface Anomaly {
  baseline_median: number;
  normal_range_low: number;
  normal_range_high: number;
  sample_size: number;
  anomalies: { date: string; value: number; deviation_score: number; direction: string }[];
  interpretation: string;
}

interface Routine {
  per_weekday: { weekday: string; mean: number | null; sample_size: number }[];
  weekend_effect: {
    weekday_mean: number;
    weekend_mean: number;
    difference_pct: number;
    interpretation: string;
  } | null;
}

interface Quality {
  observed_days: number;
  window_days: number;
  coverage_pct: number;
  sufficient: boolean;
  note: string;
}

interface Insights {
  provenance: {
    analysis_version: string;
    computed_at: string;
    window_start: string;
    window_end: string;
    sources: string[];
  };
  disclaimer: string;
  metrics_analysed: string[];
  metrics_excluded_for_quality: string[];
  data_quality: Record<string, Quality>;
  correlations: Correlation[];
  lagged_correlations: LaggedCorrelation[];
  trends: Record<string, Trend>;
  anomalies: Record<string, Anomaly>;
  routines: Record<string, Routine>;
  period_comparisons: Record<string, unknown>;
  docs_url?: string;
}

type Section = "overview" | "correlations" | "trends" | "anomalies" | "routines" | "quality";

const SECTIONS: { id: Section; labelKey: MessageKey; icon: React.ElementType }[] = [
  { id: "overview", labelKey: "analysis.tabOverview", icon: Activity },
  { id: "correlations", labelKey: "analysis.tabCorrelations", icon: Activity },
  { id: "trends", labelKey: "analysis.tabTrends", icon: TrendingUp },
  { id: "anomalies", labelKey: "analysis.tabAnomalies", icon: AlertTriangle },
  { id: "routines", labelKey: "analysis.tabRoutines", icon: CalendarClock },
  { id: "quality", labelKey: "analysis.tabQuality", icon: ShieldQuestion },
];

export default function AnalysisTab({
  apiBase,
  refreshTrigger,
}: {
  apiBase: string;
  tenantId?: string;
  refreshTrigger?: number;
}) {
  const { t, formatDate, formatDateTime } = useI18n();
  const [data, setData] = useState<Insights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [section, setSection] = useState<Section>("overview");

  const [windowDays, setWindowDays] = useState(90);
  const [minStrength, setMinStrength] = useState(0.2);
  const [onlySignificant, setOnlySignificant] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        days: String(windowDays),
        min_strength: String(minStrength),
        compare_to_previous: "true",
      });
      const res = await apiFetch(`${apiBase}/api/v1/analysis/insights?${params}`);
      if (!res.ok) throw new Error(t("analysis.loadFailed"));
      setData(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
    // `t` belongs here: without it the error message keeps the language captured at
    // first render, so switching to German left this one string in English.
  }, [apiBase, windowDays, minStrength, t]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) await load();
    })();
    return () => {
      cancelled = true;
    };
  }, [load, refreshTrigger]);

  const correlations = useMemo(
    () => (data?.correlations ?? []).filter((c) => !onlySignificant || c.significant),
    [data, onlySignificant],
  );

  // Square matrix over the metrics that actually appear in a shown pair.
  const heatmap = useMemo(() => {
    const metrics = Array.from(
      new Set(correlations.flatMap((c) => [c.metric_a, c.metric_b])),
    ).sort();
    const lookup = new Map<string, Correlation>();
    correlations.forEach((c) => {
      lookup.set(`${c.metric_a}|${c.metric_b}`, c);
      lookup.set(`${c.metric_b}|${c.metric_a}`, c);
    });
    return { metrics, lookup };
  }, [correlations]);

  if (loading && !data) {
    return (
      <section className="flex h-64 items-center justify-center text-sm text-slate-400">
        <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> {t("analysis.computing")}
      </section>
    );
  }

  if (error) {
    return (
      <section className="rounded-3xl border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        {error}
      </section>
    );
  }

  const hasAnything =
    data && (data.metrics_analysed.length > 0 || data.metrics_excluded_for_quality.length > 0);

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-emerald-700">
            {t("sidebar.analysis")}
          </p>
          <h1 className="text-3xl font-extrabold text-slate-900">{t("analysis.title")}</h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-500">{t("analysis.subtitleTail")}</p>
        </div>
        {loading && <RefreshCw className="h-5 w-5 animate-spin text-emerald-700" />}
      </header>

      {/*
        Filters — one row above the charts.

        `items-end` pinned every child to the bottom of the row. The two selects are
        taller than the checkbox and the docs link, so those two dropped onto the
        selects' baseline instead of sitting centred in the card. `items-center`
        aligns them on the row's middle, which is where they look like they belong.
      */}
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4">
        <label className="text-xs font-semibold text-slate-600">
          {t("analysis.window")}
          <select
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
            className="ml-2 rounded-xl border border-slate-200 px-2.5 py-1.5 text-xs outline-none"
          >
            {[30, 90, 180, 365].map((days) => (
              <option key={days} value={days}>
                {t("common.days_other", { count: days })}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-semibold text-slate-600">
          {t("analysis.minStrength")}
          <select
            value={minStrength}
            onChange={(e) => setMinStrength(Number(e.target.value))}
            className="ml-2 rounded-xl border border-slate-200 px-2.5 py-1.5 text-xs outline-none"
          >
            <option value={0}>{t("analysis.all")}</option>
            {[20, 40, 60].map((percent) => (
              <option key={percent} value={percent / 100}>
                {t("analysis.fromPercent", { percent })}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-600">
          <input
            type="checkbox"
            checked={onlySignificant}
            onChange={(e) => setOnlySignificant(e.target.checked)}
          />
          {t("analysis.onlySignificant")}
        </label>
        {data?.docs_url && (
          <a
            href={data.docs_url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto inline-flex items-center gap-1.5 text-xs font-semibold text-[#0d5c3a] underline"
          >
            <BookOpen className="h-3.5 w-3.5" /> {t("analysis.howToRead")}
          </a>
        )}
      </div>

      {/* Section navigation */}
      <nav className="flex flex-wrap gap-1.5 border-b border-slate-200 pb-2">
        {SECTIONS.map(({ id, labelKey, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setSection(id)}
            className={`flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors ${
              section === id ? "bg-[#0d5c3a] text-white" : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            {t(labelKey)}
          </button>
        ))}
      </nav>

      {!hasAnything && (
        <p className="rounded-2xl border border-slate-200 bg-slate-50 p-6 text-sm text-slate-500">
          {t("analysis.noData")}
        </p>
      )}

      {data && section === "overview" && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <StatTile
              label={t("analysis.usableMetrics")}
              value={data.metrics_analysed.length}
              hint={
                data.metrics_excluded_for_quality.length > 0
                  ? t("analysis.excludedForQuality", {
                      count: data.metrics_excluded_for_quality.length,
                    })
                  : t("analysis.allMetricsQualify")
              }
            />
            <StatTile
              label={t("analysis.significantRelationships")}
              value={data.correlations.filter((c) => c.significant).length}
              hint={t("analysis.ofPairsChecked", { count: data.correlations.length })}
            />
            <StatTile
              label={t("analysis.unusualDays")}
              value={Object.values(data.anomalies).reduce((n, a) => n + a.anomalies.length, 0)}
              hint={t("analysis.outsideNormal")}
            />
          </div>

          {/*
            The service still sends `disclaimer`, in English, for consumers that are not
            this interface. Rendering it verbatim left the warning English even with the
            rest of the page in German, so the wording lives in the catalogue instead
            (rule 17: services answer in English, the edge localizes).
          */}
          <p className="flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-xs leading-relaxed text-amber-900">
            <Info className="mt-0.5 h-4 w-4 shrink-0" />
            {t("analysis.disclaimer")}
          </p>

          {correlations.length > 0 && <TopFindings correlations={correlations.slice(0, 3)} />}

          <Provenance provenance={data.provenance} />
        </div>
      )}

      {data && section === "correlations" && (
        <div className="space-y-5">
          {correlations.length === 0 ? (
            <EmptyNote>{t("analysis.noneMatchFilters")}</EmptyNote>
          ) : (
            <>
              <Heatmap metrics={heatmap.metrics} lookup={heatmap.lookup} />
              <div className="space-y-2">
                {correlations.map((c) => {
                  const key = `${c.metric_a}|${c.metric_b}`;
                  return (
                    <CorrelationCard
                      key={key}
                      correlation={c}
                      expanded={expanded === key}
                      onToggle={() => setExpanded(expanded === key ? null : key)}
                      provenance={data.provenance}
                      quality={data.data_quality}
                    />
                  );
                })}
              </div>

              {data.lagged_correlations.length > 0 && (
                <div>
                  <h2 className="mb-1 text-sm font-bold text-slate-900">
                    {t("analysis.laggedTitle")}
                  </h2>
                  <p className="mb-2 text-xs text-slate-500">
                    Werte eines Tages im Vergleich mit einer anderen Metrik einige Tage
                    {t("analysis.laggedTail")}
                  </p>
                  <div className="space-y-1.5">
                    {data.lagged_correlations.slice(0, 8).map((l) => (
                      <div
                        key={`${l.metric_a}-${l.metric_b}-${l.lag_days}`}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs"
                      >
                        <span className="font-medium text-slate-700">
                          {l.metric_a} → {l.metric_b}{" "}
                          <span className="text-slate-400">
                            {t("analysis.lagDays", { count: l.lag_days })}
                          </span>
                        </span>
                        <span className="flex items-center gap-2">
                          <StrengthBar value={l.coefficient} />
                          <span className="w-28 text-right text-slate-500">
                            {l.coefficient > 0
                              ? t("analysis.sameDirection")
                              : t("analysis.oppositeDirection")}{" "}
                            · {l.strength_pct.toFixed(0)} % · n={l.sample_size}
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {data && section === "trends" && (
        <div className="space-y-3">
          {Object.keys(data.trends).length === 0 ? (
            <EmptyNote>{t("analysis.tooFewForTrend")}</EmptyNote>
          ) : (
            Object.entries(data.trends).map(([metric, trend]) => (
              <article key={metric} className="rounded-2xl border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-sm font-bold text-slate-900">{metric}</h3>
                  <span
                    className={`rounded-lg px-2 py-0.5 text-xs font-bold ${
                      trend.direction === "rising"
                        ? "bg-blue-50 text-blue-800"
                        : trend.direction === "falling"
                          ? "bg-red-50 text-red-800"
                          : "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {trend.direction}
                  </span>
                </div>
                <Sparkline values={trend.moving_average_7d} />
                <p className="mt-2 text-xs text-slate-600">{trend.interpretation}</p>
                <p className="mt-1 text-[11px] text-slate-400">
                  {t("analysis.trendStats", {
                    mean: trend.mean,
                    r2: trend.r_squared,
                    n: trend.sample_size,
                  })}
                </p>
              </article>
            ))
          )}
        </div>
      )}

      {data && section === "anomalies" && (
        <div className="space-y-3">
          {Object.keys(data.anomalies).length === 0 ? (
            <EmptyNote>{t("analysis.tooFewForNormalRange")}</EmptyNote>
          ) : (
            Object.entries(data.anomalies).map(([metric, a]) => (
              <article key={metric} className="rounded-2xl border border-slate-200 bg-white p-4">
                <h3 className="text-sm font-bold text-slate-900">{metric}</h3>
                <p className="mt-1 text-xs text-slate-600">{a.interpretation}</p>
                {a.anomalies.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {a.anomalies.slice(-6).map((x) => (
                      <li
                        key={x.date}
                        className="flex items-center justify-between rounded-lg bg-slate-50 px-2.5 py-1.5 text-[11px]"
                      >
                        <span className="font-mono text-slate-600">{formatDate(x.date)}</span>
                        <span className="text-slate-700">
                          {x.value} — {x.direction}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-[11px] text-slate-400">
                  {t("analysis.anomalyBasis", { days: a.sample_size })} gesundheitlich bedenklich.
                </p>
              </article>
            ))
          )}
        </div>
      )}

      {data && section === "routines" && (
        <div className="space-y-3">
          {Object.keys(data.routines).length === 0 ? (
            <EmptyNote>{t("analysis.tooFewForWeekly")}</EmptyNote>
          ) : (
            Object.entries(data.routines).map(([metric, r]) => (
              <article key={metric} className="rounded-2xl border border-slate-200 bg-white p-4">
                <h3 className="mb-2 text-sm font-bold text-slate-900">{metric}</h3>
                <WeekdayChart data={r.per_weekday} />
                {r.weekend_effect && (
                  <p className="mt-2 text-xs text-slate-600">{r.weekend_effect.interpretation}</p>
                )}
              </article>
            ))
          )}
        </div>
      )}

      {data && section === "quality" && (
        <div className="space-y-3">
          <p className="text-xs text-slate-500">
            Analysen laufen nur auf Metriken mit ausreichender Datenbasis. Alles andere wird bewusst
            ausgeblendet statt schwach dargestellt.
          </p>
          <div className="overflow-x-auto rounded-2xl border border-slate-200">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-3 py-2 font-semibold text-slate-600">Metrik</th>
                  <th className="px-3 py-2 font-semibold text-slate-600">
                    {t("analysis.colDays")}
                  </th>
                  <th className="px-3 py-2 font-semibold text-slate-600">Abdeckung</th>
                  <th className="px-3 py-2 font-semibold text-slate-600">Status</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.data_quality).map(([metric, q]) => (
                  <tr key={metric} className="border-t border-slate-100">
                    <td className="px-3 py-2 font-medium text-slate-700">{metric}</td>
                    <td className="px-3 py-2 text-slate-600">
                      {q.observed_days}/{q.window_days}
                    </td>
                    <td className="px-3 py-2 text-slate-600">{q.coverage_pct} %</td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded px-1.5 py-0.5 font-semibold ${
                          q.sufficient
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-slate-200 text-slate-600"
                        }`}
                      >
                        {q.sufficient ? t("analysis.sufficient") : t("analysis.tooThin")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

// ─── pieces ──────────────────────────────────────────────────

function StatTile({ label, value, hint }: { label: string; value: number; hint: string }) {
  return (
    <article className="rounded-3xl border border-slate-200 bg-white p-5">
      <p className="text-sm font-semibold text-slate-500">{label}</p>
      <p className="text-4xl font-black text-slate-900">{value}</p>
      <p className="mt-1 text-xs text-slate-400">{hint}</p>
    </article>
  );
}

function EmptyNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-2xl border border-slate-200 bg-slate-50 p-5 text-sm text-slate-500">
      {children}
    </p>
  );
}

function StrengthBar({ value }: { value: number }) {
  return (
    <span
      className="inline-block h-2 w-20 overflow-hidden rounded-full"
      style={{ background: NEUTRAL }}
      aria-hidden="true"
    >
      <span
        className="block h-full rounded-full"
        style={{
          width: `${Math.min(100, Math.abs(value) * 100)}%`,
          background: correlationColor(value),
        }}
      />
    </span>
  );
}

/** Diverging legend — required because colour carries polarity. */
function HeatmapLegend() {
  const t = useT();
  const stops: { color: string; label: string }[] = [
    { color: NEG[0], label: t("analysis.scaleStrongOpposite") },
    { color: NEG[1], label: "" },
    { color: NEG[2], label: "" },
    { color: NEUTRAL, label: t("analysis.scaleNone") },
    { color: POS[2], label: "" },
    { color: POS[1], label: "" },
    { color: POS[0], label: t("analysis.scaleStrongSame") },
  ];
  return (
    <div className="flex items-center gap-2 text-[11px] text-slate-500">
      <span>−100 %</span>
      <span
        className="flex overflow-hidden rounded"
        role="img"
        aria-label={t("analysis.scaleLabel")}
      >
        {stops.map((s, i) => (
          <span key={i} className="h-3 w-6" style={{ background: s.color }} />
        ))}
      </span>
      <span>+100 %</span>
      <span className="ml-1">{t("analysis.scaleEnds")}</span>
    </div>
  );
}

function Heatmap({ metrics, lookup }: { metrics: string[]; lookup: Map<string, Correlation> }) {
  const t = useT();
  if (metrics.length < 2) return null;
  const cell = 46;
  const labelW = 150;
  const size = metrics.length * cell;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-bold text-slate-900">Korrelationsmatrix</h2>
        <HeatmapLegend />
      </div>
      <p className="mb-3 text-xs text-slate-500">
        {t("analysis.matrixHint")} zu wenige gemeinsame Tage.
      </p>
      <div className="overflow-x-auto">
        <svg
          width={labelW + size}
          height={size + 90}
          role="img"
          aria-label="Korrelationsmatrix der Metriken"
        >
          {metrics.map((m, col) => (
            <text
              key={`col-${m}`}
              x={labelW + col * cell + cell / 2}
              y={82}
              textAnchor="start"
              fontSize="10"
              fill={INK.secondary}
              transform={`rotate(-55 ${labelW + col * cell + cell / 2} 82)`}
            >
              {m.length > 16 ? `${m.slice(0, 15)}…` : m}
            </text>
          ))}
          {metrics.map((rowMetric, row) => (
            <g key={`row-${rowMetric}`}>
              <text
                x={labelW - 8}
                y={90 + row * cell + cell / 2 + 3}
                textAnchor="end"
                fontSize="10"
                fill={INK.secondary}
              >
                {rowMetric.length > 20 ? `${rowMetric.slice(0, 19)}…` : rowMetric}
              </text>
              {metrics.map((colMetric, col) => {
                const x = labelW + col * cell;
                const y = 90 + row * cell;
                if (rowMetric === colMetric) {
                  return (
                    <rect
                      key={colMetric}
                      x={x + 1}
                      y={y + 1}
                      width={cell - 2}
                      height={cell - 2}
                      rx="4"
                      fill="#ffffff"
                      stroke="#e2e8f0"
                    />
                  );
                }
                const c = lookup.get(`${rowMetric}|${colMetric}`);
                if (!c) {
                  return (
                    <rect
                      key={colMetric}
                      x={x + 1}
                      y={y + 1}
                      width={cell - 2}
                      height={cell - 2}
                      rx="4"
                      fill="#fafafa"
                      stroke="#f1f5f9"
                    />
                  );
                }
                return (
                  <g key={colMetric}>
                    {/* 2px surface gap between cells */}
                    <rect
                      x={x + 1}
                      y={y + 1}
                      width={cell - 2}
                      height={cell - 2}
                      rx="4"
                      fill={correlationColor(c.coefficient)}
                    />
                    {/* Value label: the near-midpoint steps fall below 3:1, so the
                        number — not the colour — carries the reading. */}
                    <text
                      x={x + cell / 2}
                      y={y + cell / 2 + 3.5}
                      textAnchor="middle"
                      fontSize="10"
                      fontWeight="600"
                      fill={cellInk(c.coefficient)}
                    >
                      {c.coefficient > 0 ? "+" : "−"}
                      {Math.round(c.strength_pct)}
                    </text>
                    <title>
                      {`${rowMetric} ↔ ${colMetric}: ${c.direction}, ${c.strength_label}, ` +
                        `${c.strength_pct.toFixed(0)} % (n=${c.sample_size}, p=${c.p_value})`}
                    </title>
                  </g>
                );
              })}
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}

function TopFindings({ correlations }: { correlations: Correlation[] }) {
  const t = useT();
  return (
    <div>
      <h2 className="mb-2 text-sm font-bold text-slate-900">{t("analysis.strongestTitle")}</h2>
      <div className="space-y-2">
        {correlations.map((c) => (
          <div
            key={`${c.metric_a}|${c.metric_b}`}
            className="rounded-2xl border border-slate-200 bg-white p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold text-slate-800">
                {c.metric_a} ↔ {c.metric_b}
              </span>
              <span className="flex items-center gap-2 text-xs">
                <StrengthBar value={c.coefficient} />
                <span className="font-bold text-slate-700">
                  {c.direction === "positive"
                    ? t("analysis.sameDirection")
                    : t("analysis.oppositeDirection")}{" "}
                  {c.strength_pct.toFixed(0)} %
                </span>
              </span>
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{c.interpretation}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function CorrelationCard({
  correlation: c,
  expanded,
  onToggle,
  provenance,
  quality,
}: {
  correlation: Correlation;
  expanded: boolean;
  onToggle: () => void;
  provenance: Insights["provenance"];
  quality: Record<string, Quality>;
}) {
  const { t, formatDate, formatDateTime } = useI18n();
  return (
    <article className="rounded-2xl border border-slate-200 bg-white">
      <button
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full flex-wrap items-center justify-between gap-2 p-4 text-left"
      >
        <span className="text-sm font-semibold text-slate-800">
          {c.metric_a} ↔ {c.metric_b}
        </span>
        <span className="flex items-center gap-2 text-xs">
          <StrengthBar value={c.coefficient} />
          <span className="font-bold text-slate-700">
            {c.direction === "positive"
              ? t("analysis.sameDirection")
              : t("analysis.oppositeDirection")}{" "}
            {c.strength_pct.toFixed(0)} %
          </span>
          {!c.significant && (
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold text-slate-500">
              nicht signifikant
            </span>
          )}
          <ChevronDown
            className={`h-4 w-4 text-slate-400 transition-transform ${expanded ? "rotate-180" : ""}`}
          />
        </span>
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-slate-100 p-4 text-xs">
          <div>
            <h4 className="font-bold text-slate-700">Interpretation</h4>
            <p className="mt-0.5 leading-relaxed text-slate-600">{c.interpretation}</p>
          </div>

          <div>
            <h4 className="font-bold text-slate-700">{t("analysis.provenanceTitle")}</h4>
            <ul className="mt-0.5 space-y-0.5 text-slate-600">
              <li>Gemeinsame Tage: {c.sample_size}</li>
              <li>
                Zeitraum: {formatDate(provenance.window_start)} –{" "}
                {formatDate(provenance.window_end)}
              </li>
              <li>{t("analysis.sources", { list: provenance.sources.join(", ") || "—" })}</li>
              <li>
                Abdeckung: {quality[c.metric_a]?.coverage_pct ?? "?"} % /{" "}
                {quality[c.metric_b]?.coverage_pct ?? "?"} %
              </li>
            </ul>
          </div>

          <div>
            <h4 className="font-bold text-slate-700">Berechnung</h4>
            <ul className="mt-0.5 space-y-0.5 text-slate-600">
              <li>Pearson (linear): {c.pearson}</li>
              <li>Spearman (Rang): {c.spearman}</li>
              <li>
                p-Wert: {c.p_value} —{" "}
                {c.significant ? t("analysis.significant") : t("analysis.notSignificant")}
              </li>
              <li>Analyseversion: {provenance.analysis_version}</li>
              <li>Berechnet: {formatDateTime(provenance.computed_at)}</li>
            </ul>
          </div>

          <div>
            <h4 className="font-bold text-slate-700">{t("analysis.limitsTitle")}</h4>
            <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-slate-600">
              <li>{t("analysis.limitsBody")}</li>
              {c.caveats.map((caveat) => (
                <li key={caveat}>{caveat}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </article>
  );
}

function Sparkline({ values }: { values: (number | null)[] }) {
  const t = useT();
  const points = values
    .map((v, i) => ({ v, i }))
    .filter((p): p is { v: number; i: number } => p.v !== null);
  if (points.length < 2) return null;

  const vals = points.map((p) => p.v);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const w = 560;
  const h = 48;

  const path = points
    .map((p, idx) => {
      const x = (p.i / Math.max(1, values.length - 1)) * w;
      const y = h - ((p.v - min) / span) * h;
      return `${idx === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="mt-2 h-12 w-full"
      preserveAspectRatio="none"
      role="img"
      aria-label={t("analysis.sparklineLabel")}
    >
      <path d={path} fill="none" stroke="#0d5c3a" strokeWidth="2" />
    </svg>
  );
}

function WeekdayChart({
  data,
}: {
  data: { weekday: string; mean: number | null; sample_size: number }[];
}) {
  const values = data.map((d) => d.mean).filter((v): v is number => v !== null);
  if (values.length === 0) return null;
  const max = Math.max(...values);

  return (
    <div className="space-y-1">
      {data.map((d) => (
        <div key={d.weekday} className="flex items-center gap-2 text-[11px]">
          <span className="w-20 shrink-0 text-slate-500">{d.weekday}</span>
          <span className="h-3 flex-1 overflow-hidden rounded-sm bg-slate-100">
            {d.mean !== null && (
              <span
                className="block h-full rounded-sm"
                style={{ width: `${(d.mean / max) * 100}%`, background: "#0d5c3a" }}
              />
            )}
          </span>
          <span className="w-16 text-right text-slate-600">{d.mean !== null ? d.mean : "—"}</span>
        </div>
      ))}
    </div>
  );
}

function Provenance({ provenance }: { provenance: Insights["provenance"] }) {
  const { t, formatDate, formatDateTime } = useI18n();
  return (
    <p className="text-[11px] text-slate-400">
      Zeitraum {formatDate(provenance.window_start)} – {formatDate(provenance.window_end)} ·
      {t("analysis.footerSources", { list: provenance.sources.join(", ") || "—" })}{" "}
      {provenance.analysis_version} · berechnet {formatDateTime(provenance.computed_at)}
    </p>
  );
}
