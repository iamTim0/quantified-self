"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BookOpen,
  CalendarClock,
  Dumbbell,
  Info,
  RefreshCw,
  ShieldQuestion,
  TrendingUp,
} from "lucide-react";
import { apiFetch } from "../lib/api";
import { plural, useI18n, useT, type MessageKey, type Translate } from "../lib/i18n/provider";
import { useReport, type ReportParams } from "../lib/reports";
import { describeMetric } from "../lib/metrics/catalog";
import Disclosure from "./Disclosure";
import MetricSourcePicker from "./MetricSourcePicker";
import ReportStatus from "./ReportStatus";
import { muscleKey } from "./WorkoutsTab";

/**
 * Analysis dashboard.
 *
 * Two things govern every design decision here.
 *
 * **Nothing is presented as causal.** Correlations are labelled as associations,
 * every card repeats the sample size and significance, and the heading copy says
 * "is associated with", never "causes". A correlation shown without its
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

type NumberFormatter = (value: number, options?: Intl.NumberFormatOptions) => string;

function metricMeta(raw: string, locale: "de" | "en") {
  return describeMetric(raw, locale);
}

function metricLabel(raw: string, locale: "de" | "en", withUnit = false): string {
  const described = metricMeta(raw, locale);
  return withUnit && described.unit
    ? described.label + " (" + described.unit + ")"
    : described.label;
}

function metricValue(
  raw: string,
  value: number | null | undefined,
  locale: "de" | "en",
  formatNumber: NumberFormatter,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const described = metricMeta(raw, locale);
  const number = formatNumber(value, {
    maximumFractionDigits: described.precision,
  });
  return described.unit ? number + " " + described.unit : number;
}

function interpretationText(
  t: Translate,
  code: string | undefined,
  params: Record<string, string | number | boolean> | undefined,
  fallback: string,
  locale: "de" | "en",
  formatNumber: NumberFormatter,
): string {
  if (!code) return fallback;
  const values = params ?? {};
  const directionSuffix =
    code === "correlation_association"
      ? "Correlation"
      : code.startsWith("routine_")
        ? "Routine"
        : "";
  const direction =
    typeof values.direction === "string"
      ? t(("analysis.direction." + values.direction + directionSuffix) as MessageKey)
      : "";
  const strength =
    typeof values.strength === "string"
      ? t(("analysis.strength." + values.strength.replace(/ /g, "_")) as MessageKey)
      : "";
  const vars: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(values)) {
    if (typeof value === "boolean") continue;
    if (key === "metric_a" || key === "metric_b") {
      vars[key] = metricLabel(String(value), locale, true);
    } else if (key.endsWith("_pct")) {
      vars[key] = formatNumber(Number(value), { maximumFractionDigits: 1 });
    } else if (key === "normal_range_low" || key === "normal_range_high") {
      vars[key] = formatNumber(Number(value), { maximumFractionDigits: 2 });
    } else {
      vars[key] = value;
    }
  }
  if (direction) vars.direction = direction;
  if (strength) vars.strength = strength;
  const key = ("analysis.interpretation." + code) as MessageKey;
  const translated = t(key, vars);
  return translated === key ? fallback : translated;
}

const CORRELATION_CAVEAT_KEYS: Record<string, MessageKey> = {
  pearson_spearman_disagree: "analysis.caveat.pearson_spearman_disagree",
  small_overlap: "analysis.caveat.small_overlap",
  raw_not_significant: "analysis.caveat.raw_not_significant",
  bh_not_significant_raw_below_alpha: "analysis.caveat.bh_not_significant_raw_below_alpha",
  bh_not_significant: "analysis.caveat.bh_not_significant",
};

function correlationCaveatText(
  t: Translate,
  caveat: { code: string; params: Record<string, string | number | boolean> },
  formatNumber: NumberFormatter,
): string | null {
  const key = CORRELATION_CAVEAT_KEYS[caveat.code];
  if (!key) return null;
  const vars = Object.fromEntries(
    Object.entries(caveat.params).flatMap(([name, value]) =>
      typeof value === "number"
        ? [[name, formatNumber(value)]]
        : typeof value === "string"
          ? [[name, value]]
          : [],
    ),
  );
  return t(key, vars);
}

function reportErrorText(
  t: Translate,
  error: {
    code: string;
    params: Record<string, string | number | boolean>;
    message?: string | null;
  } | null,
): string | null {
  if (!error) return null;
  const code = error.code.startsWith("insights_failed_") ? "insights_failed" : error.code;
  const keys: Record<string, MessageKey> = {
    report_failed: "report.error.report_failed",
    insights_failed: "report.error.insights_failed",
    report_load_failed: "report.error.report_load_failed",
    report_refresh_failed: "report.error.report_refresh_failed",
  report_timeout: "report.error.report_timeout",
  report_never_claimed: "report.error.report_never_claimed",
  };
  const key = keys[code];
  if (!key) return error.message || t("report.failed");
  const vars = Object.fromEntries(
    Object.entries(error.params).filter(
      (entry): entry is [string, string | number] =>
        typeof entry[1] === "string" || typeof entry[1] === "number",
    ),
  );
  return t(key, vars);
}

function correlationColor(r: number): string {
  const a = Math.abs(r);
  if (a < 0.2) return NEUTRAL;
  const arm = r < 0 ? NEG : POS;
  if (a < 0.4) return arm[2];
  if (a < 0.7) return arm[1];
  return arm[0];
}

/** How many of the strongest relationships the overview leads with. */
const TOP_FINDINGS = 3;

/**
 * The DOM id of one pair's card, from the `metric_a|metric_b` key.
 *
 * Metric names are `[a-z0-9_]`, so the only character needing replacement is the
 * separator — but it is done here, in one place, so the matrix and the list
 * cannot disagree about the spelling.
 */
function correlationDomId(key: string): string {
  return `correlation-${key.replace("|", "--")}`;
}

/** How many lagged pairs the list shows before it states how many it is hiding. */
const LAGGED_SHOWN = 8;

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
  q_value?: number;
  multiple_testing_method?: string;
  significant: boolean;
  interpretation_code?: string;
  interpretation_params?: Record<string, string | number | boolean>;
  interpretation: string;
  caveats: string[];
  caveat_codes?: { code: string; params: Record<string, string | number | boolean> }[];
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
  significance_method?: string;
  interpretation_code?: string;
  interpretation_params?: Record<string, string | number | boolean>;
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
  interpretation_code?: string;
  interpretation_params?: Record<string, string | number | boolean>;
  interpretation: string;
}

interface Anomaly {
  baseline_median: number;
  normal_range_low: number;
  normal_range_high: number;
  sample_size: number;
  anomalies: { date: string; value: number; deviation_score: number; direction: string }[];
  interpretation_code?: string;
  interpretation_params?: Record<string, string | number | boolean>;
  interpretation: string;
}

interface Routine {
  per_weekday: { weekday: string; mean: number | null; sample_size: number }[];
  weekend_effect: {
    weekday_mean: number;
    weekend_mean: number;
    difference_pct: number;
    interpretation_code?: string;
    interpretation_params?: Record<string, string | number | boolean>;
    interpretation: string;
  } | null;
  interpretation_code?: string;
  interpretation_params?: Record<string, string | number | boolean>;
}

interface Quality {
  observed_days: number;
  window_days: number;
  coverage_pct: number;
  sufficient: boolean;
  note: string;
}

/**
 * Per-exercise progression, from `insights.strength`.
 *
 * `basis` says what "stronger" was measured *as*, because it differs per
 * exercise: a loaded lift trends on its estimated one-rep max, a high-rep lift on
 * volume, and a bodyweight exercise on repetitions — the last because its volume
 * is zero at every session and calling that flat would be a wrong answer.
 */
interface StrengthTrend {
  direction: string;
  basis: string;
  change_pct_over_window: number;
  r_squared: number;
  sample_size: number;
}

interface StrengthExercise {
  exercise_title: string;
  muscle_group: string | null;
  sessions: number;
  total_sets: number;
  total_volume_kg: number;
  best_set_weight_kg: number | null;
  best_set_day: string | null;
  latest_estimated_1rm_kg: number | null;
  trend: StrengthTrend | null;
}

interface StrengthGroup {
  muscle_group: string;
  volume_kg: number;
  sets: number;
  volume_share_pct: number | null;
  set_share_pct: number;
}

interface Strength {
  exercises: StrengthExercise[];
  muscle_groups: StrengthGroup[];
  sets_analysed: number;
  truncated: boolean;
  min_sessions_for_trend: number;
  disclaimer: string;
}

/**
 * The insights bundle **after normalisation** — the shape the components below may
 * rely on. What actually arrives is `StoredInsights`; see `normaliseInsights`.
 */
interface Insights {
  /**
   * Nullable on purpose. A run written before this field existed has no window and
   * no version, and `formatDate` already renders an absent date as "—" — which is
   * the truthful answer. A placeholder date would be a claim about when the numbers
   * were computed, and that claim is the whole point of showing provenance at all.
   */
  provenance: {
    analysis_version: string | null;
    computed_at: string | null;
    window_start: string | null;
    window_end: string | null;
    sources: string[];
  };
  disclaimer: string;
  metrics_analysed: string[];
  metrics_excluded_for_quality: string[];
  metric_source_ids?: Record<string, string[]>;
  source_issues?: {
    code: string;
    metric_type: string;
    source_ids: string[];
    /** Which source answers. Empty from a Core that could not resolve it. */
    primary_source_id?: string;
    /** `preference` or `coverage` — an identifier the client branches on (rule 17). */
    primary_reason?: string;
  }[];
  data_quality: Record<string, Quality>;
  correlations: Correlation[];
  lagged_correlations: LaggedCorrelation[];
  trends: Record<string, Trend>;
  anomalies: Record<string, Anomaly>;
  routines: Record<string, Routine>;
  period_comparisons: Record<string, unknown>;
  strength?: Strength;
  docs_url?: string;
}

/**
 * The bundle as it may actually arrive, which is not the shape this release writes.
 *
 * A precomputed report is stored and **served while stale** — `lib/reports.ts` argues
 * for that deliberately — so the first client after a deploy reads payloads the
 * *previous* release wrote, and every field this one added is missing from all of
 * them. `DailyStory` records at length what that cost: the day report gained
 * `logged`, the overview called `story.logged.reduce(...)`, and every existing
 * installation showed a blank error page after signing in.
 *
 * That fix was applied to the two fields that had broken, and this file went on
 * dereferencing seven more of its own — `Object.keys(undefined)` throws exactly as
 * loudly as `undefined.reduce`, and nothing in the type said so. A payload of `{}`
 * reproduced it in one line (`e2e/partial-reports.spec.ts`).
 *
 * **Only containers are loosened.** An absent list is honestly an empty list, so
 * `?? []` states nothing that was not true. An absent *number* is not zero, and
 * defaulting `pearson` or `coverage_pct` would put a fabricated measurement on
 * screen — indistinguishable from a real one, which is the failure AGENTS.md rule 19
 * calls worse than a gap. Missing scalars therefore stay missing and render as "—".
 */
type Loose<T, K extends keyof T> = Omit<T, K> & Partial<Pick<T, K>>;

type StoredCorrelation = Loose<Correlation, "caveats">;
type StoredTrend = Loose<Trend, "moving_average_7d">;
type StoredAnomaly = Loose<Anomaly, "anomalies">;
type StoredRoutine = Loose<Routine, "per_weekday">;
type StoredStrength = Loose<Strength, "exercises" | "muscle_groups">;

export type StoredInsights = Loose<
  Omit<Insights, "provenance" | "correlations" | "trends" | "anomalies" | "routines" | "strength">,
  | "metrics_analysed"
  | "metrics_excluded_for_quality"
  | "data_quality"
  | "lagged_correlations"
> & {
  provenance?: Partial<Insights["provenance"]>;
  correlations?: StoredCorrelation[];
  trends?: Record<string, StoredTrend>;
  anomalies?: Record<string, StoredAnomaly>;
  routines?: Record<string, StoredRoutine>;
  strength?: StoredStrength;
};

/** Fill the containers of a record's values, leaving the keys and scalars alone. */
function normaliseRecord<S, T>(
  stored: Record<string, S> | undefined,
  normalise: (value: S) => T,
): Record<string, T> {
  return Object.fromEntries(
    Object.entries(stored ?? {}).map(([key, value]) => [key, normalise(value)]),
  );
}

/**
 * One stored bundle, filled out to the shape the components below require.
 *
 * Normalised here rather than guarded at each of the reads, for the reason
 * `normaliseStory` gives: a guard per call site is a rule enforced by memory, so the
 * next field added gets dereferenced raw by whoever adds it and the failure returns
 * one release later. Adding a container to the bundle now means deciding its default
 * in this one function.
 *
 * Nested containers are filled too, because a crash does not care how deep the
 * missing list sits — `a.anomalies.length` and `strength.muscle_groups.map` are the
 * same defect one level down.
 */
function normaliseInsights(stored: StoredInsights): Insights {
  return {
    ...stored,
    provenance: {
      analysis_version: stored.provenance?.analysis_version ?? null,
      computed_at: stored.provenance?.computed_at ?? null,
      window_start: stored.provenance?.window_start ?? null,
      window_end: stored.provenance?.window_end ?? null,
      sources: stored.provenance?.sources ?? [],
    },
    metrics_analysed: stored.metrics_analysed ?? [],
    metrics_excluded_for_quality: stored.metrics_excluded_for_quality ?? [],
    data_quality: stored.data_quality ?? {},
    correlations: (stored.correlations ?? []).map((c) => ({ ...c, caveats: c.caveats ?? [] })),
    lagged_correlations: stored.lagged_correlations ?? [],
    trends: normaliseRecord(stored.trends, (trend) => ({
      ...trend,
      moving_average_7d: trend.moving_average_7d ?? [],
    })),
    anomalies: normaliseRecord(stored.anomalies, (anomaly) => ({
      ...anomaly,
      anomalies: anomaly.anomalies ?? [],
    })),
    routines: normaliseRecord(stored.routines, (routine) => ({
      ...routine,
      per_weekday: routine.per_weekday ?? [],
    })),
    strength: stored.strength
      ? {
          ...stored.strength,
          exercises: stored.strength.exercises ?? [],
          muscle_groups: stored.strength.muscle_groups ?? [],
        }
      : undefined,
  };
}

interface AnalysisSource {
  id: string;
  source_type: string;
  display_name?: string;
}

type Section =
  | "overview"
  | "correlations"
  | "trends"
  | "strength"
  | "anomalies"
  | "routines"
  | "quality";

const SECTIONS: { id: Section; labelKey: MessageKey; icon: React.ElementType }[] = [
  { id: "overview", labelKey: "analysis.tabOverview", icon: Activity },
  { id: "correlations", labelKey: "analysis.tabCorrelations", icon: Activity },
  { id: "trends", labelKey: "analysis.tabTrends", icon: TrendingUp },
  { id: "strength", labelKey: "analysis.tabStrength", icon: Dumbbell },
  { id: "anomalies", labelKey: "analysis.tabAnomalies", icon: AlertTriangle },
  { id: "routines", labelKey: "analysis.tabRoutines", icon: CalendarClock },
  { id: "quality", labelKey: "analysis.tabQuality", icon: ShieldQuestion },
];

/**
 * Per-exercise progression.
 *
 * Its own component so `strength` arrives non-optional: inline, TypeScript loses
 * the narrowing from the guard the moment the value is read inside a `.map()`
 * callback, and the alternative is a non-null assertion on every line.
 */
function StrengthSection({ strength, weightUnit }: { strength: Strength; weightUnit: string }) {
  const { t, formatNumber } = useI18n();
  return (
    <>
      <p className="text-xs text-ink-muted">
        {t("analysis.strengthDisclaimer")}
      </p>
      {strength.truncated && (
        <p className="text-xs text-warn-ink">{t("analysis.strengthTruncated")}</p>
      )}

      {strength.muscle_groups.length > 0 && (
        <article className="rounded-2xl border border-line bg-surface p-4">
          <h3 className="mb-1 text-sm font-bold text-ink">
            {t("analysis.strengthBalance")}
          </h3>
          <p className="mb-3 text-xs text-ink-muted">
            {t("analysis.strengthBalanceHint")}
          </p>
          <div className="space-y-1.5">
            {strength.muscle_groups.map((group) => (
              <div key={group.muscle_group} className="flex items-center gap-2">
                <span className="w-28 shrink-0 truncate text-xs text-ink-muted">
                  {t(muscleKey(group.muscle_group))}
                </span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-muted">
                  <div
                    className="h-full rounded-full bg-[#1d4ed8] dark:bg-[#60a5fa]"
                    style={{ width: `${group.set_share_pct}%` }}
                  />
                </div>
                <span className="w-24 shrink-0 text-right text-meta text-ink-muted">
                  {t(plural(group.sets, "workouts.sets_one", "workouts.sets_other"), {
                    count: group.sets,
                  })}
                </span>
              </div>
            ))}
          </div>
        </article>
      )}

      <div className="overflow-x-auto rounded-2xl border border-line">
        <table className="w-full min-w-[560px] text-xs">
          <thead className="bg-page text-left">
            <tr>
              <th className="px-3 py-2 font-semibold text-ink-muted">
                {t("analysis.strengthExercise")}
              </th>
              <th className="px-3 py-2 font-semibold text-ink-muted">
                {t("analysis.strengthSessions")}
              </th>
              <th className="px-3 py-2 font-semibold text-ink-muted">
                {t("analysis.strengthBest")}
              </th>
              <th className="px-3 py-2 font-semibold text-ink-muted">
                {t("analysis.strengthOneRm")}
              </th>
              <th className="px-3 py-2 font-semibold text-ink-muted">
                {t("analysis.strengthDirection")}
              </th>
            </tr>
          </thead>
          <tbody>
            {strength.exercises.map((exercise) => (
              <tr
                key={exercise.exercise_title}
                className="border-t border-line"
              >
                <td className="px-3 py-2">
                  <span className="font-semibold text-ink-secondary">
                    {exercise.exercise_title}
                  </span>
                  {exercise.muscle_group && (
                    <span className="ml-2 rounded-full bg-surface-muted px-2 py-0.5 text-meta text-ink-muted">
                      {t(muscleKey(exercise.muscle_group))}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-ink-muted">
                  {exercise.sessions}
                </td>
                <td className="px-3 py-2 text-ink-muted">
                  {exercise.best_set_weight_kg === null
                    ? "—"
                    : `${formatNumber(exercise.best_set_weight_kg)} ${weightUnit}`}
                </td>
                <td className="px-3 py-2 text-ink-muted">
                  {exercise.latest_estimated_1rm_kg === null
                    ? "—"
                    : `${formatNumber(exercise.latest_estimated_1rm_kg)} ${weightUnit}`}
                </td>
                <td className="px-3 py-2">
                  {exercise.trend === null ? (
                    <span
                      className="text-ink-muted"
                      title={t("analysis.strengthTooFew", {
                        count: strength.min_sessions_for_trend,
                      })}
                    >
                      —
                    </span>
                  ) : (
                    <span
                      className={
                        exercise.trend.direction === "rising"
                          ? "font-semibold text-[#1d4ed8] dark:text-[#93c5fd]"
                          : exercise.trend.direction === "falling"
                            ? "font-semibold text-[#b91c1c] dark:text-[#fda4af]"
                            : "text-ink-muted"
                      }
                      title={t(`analysis.strengthBasis.${exercise.trend.basis}` as MessageKey)}
                    >
                      {t(`analysis.direction.${exercise.trend.direction}` as MessageKey)}{" "}
                      <span className="font-normal text-ink-muted">
                        {exercise.trend.change_pct_over_window > 0 ? "+" : ""}
                        {formatNumber(exercise.trend.change_pct_over_window)} %
                      </span>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function AnalysisTab({
  apiBase,
  tenantId,
  refreshTrigger,
}: {
  apiBase: string;
  tenantId?: string;
  refreshTrigger?: number;
}) {
  const { t, locale, formatDay, formatNumber } = useI18n();
  // From the registry: the unit a set weight is stored in is declared once.
  const weightUnit = describeMetric("strength_set_weight", locale).unit;
  const [section, setSection] = useState<Section>("overview");

  const [minStrength, setMinStrength] = useState(0.2);
  const [onlySignificant, setOnlySignificant] = useState(true);
  const [sources, setSources] = useState<AnalysisSource[]>([]);

  /**
   * The bundle comes from a scheduled run, not from this page opening.
   *
   * It is a paged read of the whole window followed by correlations, lagged
   * correlations, trends, anomalies, weekday patterns and period comparisons —
   * so its cost grew with the amount of data a workspace held, and two readers
   * opening this tab paid it twice for one answer. Core queues a run when the
   * data changes; the Analysis Service computes it; this reads the result.
   *
   * `windowDays` and `selectedSource` change what is computed, so they ask for a
   * new run. `minStrength` does not: the coefficients are all in the payload, so
   * it filters what is already here and applies instantly.
   */
  const report = useReport<StoredInsights>(apiBase, "insights");
  // The one place the stored shape becomes the shape everything below relies on.
  const stored = report.result;
  // Memoised on the stored payload, not rebuilt per render: `correlations`, the
  // heatmap and `topFindings` are all keyed on `data`, so a fresh object each render
  // made those three `useMemo`s recompute every time and buy nothing. The inline
  // spread this replaced had the same flaw, quietly.
  const data = useMemo(() => (stored ? normaliseInsights(stored) : null), [stored]);
  const loading = report.loading || report.running;
  // The window and connector the stored run used. Read from the run rather than
  // held in state, so the selectors always show what is on screen rather than
  // what was last clicked.
  const windowDays = Number(report.params?.days ?? 90);
  const selectedSource = String(report.params?.source_id ?? "all");

  const requestRun = useCallback(
    (days: number, sourceId: string) => {
      const params: ReportParams = { days, compare_to_previous: true };
      if (sourceId !== "all") params.source_id = sourceId;
      void report.refresh(params);
    },
    [report],
  );

  const loadSources = useCallback(async () => {
    const sourceRes = await apiFetch(`${apiBase}/api/v1/data/sources`, {
      headers: tenantId ? { "X-Tenant-ID": tenantId } : undefined,
    });
    if (sourceRes.ok) {
      const sourceData = (await sourceRes.json()) as { connectors?: AnalysisSource[] };
      setSources(sourceData.connectors ?? []);
    }
  }, [apiBase, tenantId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) await loadSources();
    })();
    return () => {
      cancelled = true;
    };
  }, [loadSources, refreshTrigger]);

  const correlations = useMemo(
    () =>
      (data?.correlations ?? []).filter(
        (c) =>
          (!onlySignificant || c.significant) &&
          // Applied here, not sent to the server. The stored bundle is computed
          // with no strength floor so that changing this filters instantly
          // instead of queueing a run — but the filter has to actually exist:
          // for a while the selector was bound to state nothing read, so picking
          // "moderate" changed nothing and two comments claimed otherwise.
          Math.abs(c.coefficient) >= minStrength,
      ),
    [data, minStrength, onlySignificant],
  );

  /**
   * The strongest relationships, sorted here rather than assumed.
   *
   * This was `correlations.slice(0, 3)` under a heading that says "strongest",
   * which rested on an unstated promise that the server returns them in that
   * order. Sorting by |coefficient| costs nothing and makes the heading true of
   * whatever arrives.
   */
  /**
   * A matrix cell is a shortcut to that pair's card.
   *
   * The cards are native `<details>` now, so "open it" is a property and a
   * scroll rather than a piece of React state shared between the matrix and the
   * list. `scroll-padding` on `html` is what keeps the card clear of the sticky
   * header once it arrives.
   */
  const openCorrelation = useCallback((key: string) => {
    const target = document.getElementById(correlationDomId(key));
    if (!(target instanceof HTMLDetailsElement)) return;
    target.open = true;
    target.scrollIntoView({ block: "start", behavior: "smooth" });
  }, []);

  const topFindings = useMemo(
    () =>
      [...correlations]
        .sort((a, b) => Math.abs(b.coefficient) - Math.abs(a.coefficient))
        .slice(0, TOP_FINDINGS),
    [correlations],
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

  if (loading && !data && !report.error) {
    return (
      <section className="flex h-64 items-center justify-center text-sm text-ink-muted">
        <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> {t("analysis.computing")}
      </section>
    );
  }

  // No run has ever finished for this workspace. Not an error — the bundle is
  // computed after an import, and this is what a reader sees before the first
  // one has run. The button is the way out, so it is offered rather than hidden.
  if (
    report.status === "never_computed" &&
    !report.loading &&
    !report.running &&
    (!data || report.error)
  ) {
    return (
      <section className="space-y-4 rounded-3xl border border-line bg-surface p-6">
        {report.error ? (
          <p
            role="alert"
            className="rounded-2xl border border-danger-line bg-danger-soft p-4 text-sm text-danger-ink-on-soft"
          >
            {reportErrorText(t, report.error)}
          </p>
        ) : (
          <p className="text-sm text-ink-muted">
            {t("report.pendingFirstRun")}
          </p>
        )}
        <ReportStatus
          computedAt={null}
          stale={false}
          running={report.running}
          neverComputed
          error={report.error}
          onRefresh={() => requestRun(windowDays, selectedSource)}
        />
      </section>
    );
  }

  const hasAnything =
    data && (data.metrics_analysed.length > 0 || data.metrics_excluded_for_quality.length > 0);

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-ok-ink">
            {t("sidebar.analysis")}
          </p>
          <h1 className="text-3xl font-extrabold text-ink">
            {t("analysis.title")}
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-muted">
            {t("analysis.subtitleTail")}
          </p>
        </div>
        {loading && <RefreshCw className="h-5 w-5 animate-spin text-ok-ink" />}
      </header>

      <ReportStatus
        computedAt={report.computed_at}
        stale={report.stale}
        deferred={report.deferred}
        running={report.running}
        neverComputed={report.status === "never_computed"}
        error={report.error}
        onRefresh={() => requestRun(windowDays, selectedSource)}
      />

      {report.error && (
        <p
          role="alert"
          className="rounded-2xl border border-danger-line bg-danger-soft p-4 text-xs leading-relaxed text-danger-ink-on-soft"
        >
          {reportErrorText(t, report.error)}
        </p>
      )}

      {/*
        Which run, as opposed to what is shown.

        These two selects and the four below used to sit in one row and look
        identical, and they are not remotely the same kind of control. Window and
        source define *what gets computed*: changing either discards the stored
        bundle and queues a run that takes minutes. Minimum strength and
        significance filter coefficients that are already in the browser and apply
        in the same frame.

        A reader who thinks they are adjusting a filter and instead throws away
        the answer they were reading has been misled by the interface, not by
        their own carelessness. So the run parameters live here, in the line that
        already describes the run — beside "computed at 06:00" — behind a
        disclosure that names what they do.
      */}
      <Disclosure
        title={t("analysis.runTitle")}
        meta={t("analysis.runSummary", {
          days: windowDays,
          source:
            selectedSource === "all"
              ? t("analysis.allSources")
              : (sources.find((source) => source.id === selectedSource)?.display_name ??
                t("common.unknown")),
        })}
        note={t("analysis.runNote")}
        className=""
      >
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-xs font-semibold text-ink-muted">
            {t("analysis.window")}
            <select
              value={windowDays}
              onChange={(e) => requestRun(Number(e.target.value), selectedSource)}
              disabled={report.running}
              className="ml-2 min-h-11 rounded-xl border border-line bg-surface px-2.5 text-xs outline-none focus-ring disabled:opacity-50"
            >
              {[30, 90, 180, 365].map((days) => (
                <option key={days} value={days}>
                  {t("common.days_other", { count: days })}
                </option>
              ))}
            </select>
          </label>
          {sources.length > 0 && (
            <label className="text-xs font-semibold text-ink-muted">
              {t("analysis.source")}
              <select
                value={selectedSource}
                onChange={(e) => requestRun(windowDays, e.target.value)}
                disabled={report.running}
                className="ml-2 min-h-11 max-w-56 rounded-xl border border-line bg-surface px-2.5 text-xs outline-none focus-ring disabled:opacity-50"
              >
                <option value="all">{t("analysis.allSources")}</option>
                {sources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.display_name || source.source_type}
                  </option>
                ))}
              </select>
            </label>
          )}
          {data?.docs_url && (
            <a
              href={data.docs_url}
              target="_blank"
              rel="noreferrer"
              className="ml-auto inline-flex min-h-11 items-center gap-1.5 text-xs font-semibold text-brand underline"
            >
              <BookOpen className="h-3.5 w-3.5" /> {t("analysis.howToRead")}
            </a>
          )}
        </div>
      </Disclosure>

      {/* Section navigation */}
      <nav className="flex flex-wrap gap-1.5 border-b border-line pb-2">
        {SECTIONS.map(({ id, labelKey, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setSection(id)}
            className={`flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors ${
              section === id
                ? "bg-brand text-brand-ink"
                : "text-ink-muted hover:bg-surface-muted  "
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            {t(labelKey)}
          </button>
        ))}
      </nav>

      {!hasAnything && (
        <p className="rounded-2xl border border-line bg-page p-6 text-sm text-ink-muted">
          {t("analysis.noData")}
        </p>
      )}

      {data && section === "overview" && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <StatTile
              label={t("analysis.usableMetrics")}
              value={formatNumber(data.metrics_analysed.length)}
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
              value={formatNumber(data.correlations.filter((c) => c.significant).length)}
              hint={t("analysis.ofPairsChecked", { count: data.correlations.length })}
            />
            <StatTile
              label={t("analysis.unusualDays")}
              value={formatNumber(
                Object.values(data.anomalies).reduce((n, a) => n + a.anomalies.length, 0),
              )}
              hint={t("analysis.outsideNormal")}
            />
          </div>

          {/*
            Two different situations, and conflating them is what made the old
            single notice misleading. A metric with a primary source *is* being
            analysed, attributed to one connector; a metric without one is still
            left out. Only the second is a gap the reader has to act on.
          */}
          {(data.source_issues?.length ?? 0) > 0 && (
            <div className="space-y-3">
              {(() => {
                const issues = data.source_issues ?? [];
                const resolved = issues.filter((issue) => issue.primary_source_id);
                const unresolved = issues.length - resolved.length;
                return (
                  <>
                    {resolved.length > 0 && (
                      <p className="rounded-2xl border border-info-line bg-info-soft p-4 text-xs leading-relaxed text-info-ink">
                        {t("analysis.ambiguousSources", { count: resolved.length })}
                      </p>
                    )}
                    {unresolved > 0 && (
                      <p className="rounded-2xl border border-warn-line bg-warn-soft p-4 text-xs leading-relaxed text-warn-ink">
                        {t("analysis.ambiguousUnresolved", { count: unresolved })}
                      </p>
                    )}
                  </>
                );
              })()}
              <MetricSourcePicker apiBase={apiBase} />
            </div>
          )}

          {/*
            The service still sends `disclaimer`, in English, for consumers that are not
            this interface. Rendering it verbatim left the warning English even with the
            rest of the page in German, so the wording lives in the catalogue instead
            (rule 17: services answer in English, the edge localizes).
          */}
          <p className="flex items-start gap-2 rounded-2xl border border-warn-line bg-warn-soft p-4 text-xs leading-relaxed text-warn-ink">
            <Info className="mt-0.5 h-4 w-4 shrink-0" />
            {t("analysis.disclaimer")}
          </p>

          {topFindings.length > 0 && <TopFindings correlations={topFindings} />}

          <Disclosure
            title={t("analysis.provenanceTitle")}
            className=""
          >
            <Provenance provenance={data.provenance} />
          </Disclosure>
        </div>
      )}

      {data && section === "correlations" && (
        <div className="space-y-5">
          {/* The display filters, next to the list they filter. Unlike the run
              parameters above they change nothing on the server and cost nothing
              to undo. */}
          <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-line bg-surface p-3">
            <label className="text-xs font-semibold text-ink-muted">
              {t("analysis.minStrength")}
              <select
                value={minStrength}
                onChange={(e) => setMinStrength(Number(e.target.value))}
                className="ml-2 min-h-11 rounded-xl border border-line bg-surface px-2.5 text-xs outline-none focus-ring"
              >
                <option value={0}>{t("analysis.all")}</option>
                {[20, 40, 60].map((percent) => (
                  <option key={percent} value={percent / 100}>
                    {t("analysis.fromPercent", { percent })}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-h-11 items-center gap-1.5 text-xs font-semibold text-ink-muted">
              <input
                type="checkbox"
                checked={onlySignificant}
                onChange={(e) => setOnlySignificant(e.target.checked)}
              />
              {t("analysis.onlySignificant")}
            </label>
          </div>

          {correlations.length === 0 ? (
            <EmptyNote>{t("analysis.noneMatchFilters")}</EmptyNote>
          ) : (
            <>
              <Disclosure
                title={t("analysis.explainerTitle")}
                className=""
              >
                <AnalysisExplainer />
              </Disclosure>

              {/* `mountOnOpen`: the matrix is a wide sticky-header table that
                  measures itself, and it is the expert artifact — the cards below
                  are the answer, this is the tool for interrogating it. */}
              <Disclosure
                title={t("analysis.matrixTitle")}
                meta={t("analysis.matrixSize", { count: heatmap.metrics.length })}
                mountOnOpen
                className=""
              >
                <Heatmap
                  metrics={heatmap.metrics}
                  lookup={heatmap.lookup}
                  correlations={correlations}
                  onSelect={openCorrelation}
                />
              </Disclosure>

              <div className="space-y-2">
                {correlations.map((c) => (
                  <CorrelationCard
                    key={`${c.metric_a}|${c.metric_b}`}
                    correlation={c}
                    provenance={data.provenance}
                    quality={data.data_quality}
                  />
                ))}

              </div>

              {data.lagged_correlations.length > 0 && (
                <Disclosure
                  title={t("analysis.laggedTitle")}
                  meta={t("analysis.sampleSize", {
                    count: formatNumber(data.lagged_correlations.length),
                  })}
                  className=""
                >
                  <p className="mb-2 text-xs text-ink-muted">
                    {t("analysis.laggedTail")}
                  </p>
                  <div className="space-y-1.5">
                    {data.lagged_correlations.slice(0, LAGGED_SHOWN).map((l) => (
                      <div
                        key={`${l.metric_a}-${l.metric_b}-${l.lag_days}`}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-xs"
                      >
                        <span className="font-medium text-ink-secondary">
                          {metricLabel(l.metric_a, locale, true)} →{" "}
                          {metricLabel(l.metric_b, locale, true)}{" "}
                          <span className="text-ink-muted">
                            {t("analysis.lagDays", { count: l.lag_days })}
                          </span>
                        </span>
                        <span className="flex items-center gap-2">
                          <StrengthBar value={l.coefficient} />
                          <span className="w-28 text-right text-ink-muted">
                            {l.coefficient > 0
                              ? t("analysis.sameDirection")
                              : t("analysis.oppositeDirection")}{" "}
                            ·{" "}
                            {t("analysis.coefficientShort", {
                              value: formatNumber(l.coefficient, {
                                maximumFractionDigits: 2,
                                signDisplay: "always",
                              }),
                            })}{" "}
                            · {t("analysis.sampleSize", { count: formatNumber(l.sample_size) })}
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                  {/* Says how many are hidden. This truncated at eight in silence,
                      in the section whose entire subject is honest uncertainty. */}
                  {data.lagged_correlations.length > LAGGED_SHOWN && (
                    <p className="mt-2 text-xs text-ink-muted">
                      {t("analysis.laggedTruncated", {
                        shown: LAGGED_SHOWN,
                        total: data.lagged_correlations.length,
                      })}
                    </p>
                  )}
                  <p className="mt-2 rounded-xl bg-warn-soft px-3 py-2 text-xs text-warn-ink">
                    {t("analysis.laggedExploratory")}
                  </p>
                </Disclosure>
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
              <article
                key={metric}
                className="rounded-2xl border border-line bg-surface p-4"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-sm font-bold text-ink">
                    {metricLabel(metric, locale, true)}
                  </h3>
                  <span
                    className={`rounded-lg px-2 py-0.5 text-xs font-bold ${
                      trend.direction === "rising"
                        ? "bg-info-soft text-info-ink"
                        : trend.direction === "falling"
                          ? "bg-danger-soft text-danger-ink-on-soft"
                          : "bg-surface-muted text-ink-muted"
                    }`}
                  >
                    {t(("analysis.direction." + trend.direction) as MessageKey)}
                  </span>
                </div>
                <Sparkline values={trend.moving_average_7d} />
                <p className="mt-2 text-xs text-ink-muted">
                  {interpretationText(
                    t,
                    trend.interpretation_code,
                    trend.interpretation_params,
                    trend.interpretation,
                    locale,
                    formatNumber,
                  )}
                </p>
                <p className="mt-1 text-meta text-ink-muted">
                  {t("analysis.trendStats", {
                    mean: metricValue(metric, trend.mean, locale, formatNumber),
                    r2: formatNumber(trend.r_squared, { maximumFractionDigits: 3 }),
                    n: formatNumber(trend.sample_size),
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
              <article
                key={metric}
                className="rounded-2xl border border-line bg-surface p-4"
              >
                <h3 className="text-sm font-bold text-ink">
                  {metricLabel(metric, locale, true)}
                </h3>
                <p className="mt-1 text-xs text-ink-muted">
                  {interpretationText(
                    t,
                    a.interpretation_code,
                    a.interpretation_params,
                    a.interpretation,
                    locale,
                    formatNumber,
                  )}
                </p>
                {a.anomalies.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {a.anomalies.slice(-6).map((x) => (
                      <li
                        key={x.date}
                        className="flex items-center justify-between rounded-lg bg-page px-2.5 py-1.5 text-meta"
                      >
                        <span className="font-mono text-ink-muted">
                          {formatDay(x.date)}
                        </span>
                        <span className="text-ink-secondary">
                          {metricValue(metric, x.value, locale, formatNumber)} —{" "}
                          {t(
                            ("analysis.anomalyDirection." +
                              x.direction.replace(/ /g, "_")) as MessageKey,
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-meta text-ink-muted">
                  {t("analysis.anomalyBasis", { days: formatNumber(a.sample_size) })}
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
              <article
                key={metric}
                className="rounded-2xl border border-line bg-surface p-4"
              >
                <h3 className="mb-2 text-sm font-bold text-ink">
                  {metricLabel(metric, locale, true)}
                </h3>
                <WeekdayChart
                  data={r.per_weekday}
                  metric={metric}
                  locale={locale}
                  formatNumber={formatNumber}
                />
                {r.weekend_effect && (
                  <p className="mt-2 text-xs text-ink-muted">
                    {interpretationText(
                      t,
                      r.weekend_effect.interpretation_code,
                      r.weekend_effect.interpretation_params,
                      r.weekend_effect.interpretation,
                      locale,
                      formatNumber,
                    )}
                  </p>
                )}
              </article>
            ))
          )}
        </div>
      )}

      {data && section === "strength" && (
        <div className="space-y-4">
          {!data.strength || data.strength.exercises.length === 0 ? (
            <EmptyNote>{t("analysis.strengthEmpty")}</EmptyNote>
          ) : (
            <StrengthSection strength={data.strength} weightUnit={weightUnit} />
          )}
        </div>
      )}

      {data && section === "quality" && (
        <div className="space-y-3">
          <p className="text-xs text-ink-muted">{t("analysis.qualityHint")}</p>
          <div className="overflow-x-auto rounded-2xl border border-line">
            <table className="w-full text-xs">
              <thead className="bg-page text-left">
                <tr>
                  <th className="px-3 py-2 font-semibold text-ink-muted">
                    {t("analysis.metricLabel")}
                  </th>
                  <th className="px-3 py-2 font-semibold text-ink-muted">
                    {t("analysis.colDays")}
                  </th>
                  <th className="px-3 py-2 font-semibold text-ink-muted">
                    {t("analysis.coverageLabel")}
                  </th>
                  <th className="px-3 py-2 font-semibold text-ink-muted">
                    {t("analysis.statusLabel")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.data_quality).map(([metric, q]) => (
                  <tr key={metric} className="border-t border-line">
                    <td className="px-3 py-2 font-medium text-ink-secondary">
                      {metricLabel(metric, locale, true)}
                    </td>
                    <td className="px-3 py-2 text-ink-muted">
                      {formatNumber(q.observed_days)}/{formatNumber(q.window_days)}
                    </td>
                    <td className="px-3 py-2 text-ink-muted">
                      {formatNumber(q.coverage_pct, { maximumFractionDigits: 1 })} %
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded px-1.5 py-0.5 font-semibold ${
                          q.sufficient
                            ? "bg-ok-soft text-ok-ink"
                            : "bg-surface-muted text-ink-muted "
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

function StatTile({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <article className="rounded-3xl border border-line bg-surface p-5">
      <p className="text-sm font-semibold text-ink-muted">{label}</p>
      <p className="text-4xl font-black text-ink">{value}</p>
      <p className="mt-1 text-xs text-ink-muted">{hint}</p>
    </article>
  );
}

function EmptyNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-2xl border border-line bg-page p-5 text-sm text-ink-muted">
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
    <div className="flex items-center gap-2 text-meta text-ink-muted">
      <span>{t("analysis.scaleMin")}</span>
      <span
        className="flex overflow-hidden rounded"
        role="img"
        aria-label={t("analysis.scaleLabel")}
      >
        {stops.map((s, i) => (
          <span key={i} className="h-3 w-6" style={{ background: s.color }} />
        ))}
      </span>
      <span>{t("analysis.scaleMax")}</span>
      <span className="ml-1">{t("analysis.scaleEnds")}</span>
    </div>
  );
}

function AnalysisExplainer() {
  const t = useT();
  return (
    <article className="rounded-2xl border border-info-line bg-info-soft p-4">
      <h2 className="mb-2 text-sm font-bold text-info-ink">
        {t("analysis.explainerTitle")}
      </h2>
      <div className="grid gap-3 text-xs leading-relaxed text-info-ink sm:grid-cols-3">
        <div>
          <h3 className="font-bold">{t("analysis.explainerWhatTitle")}</h3>
          <p>{t("analysis.explainerWhat")}</p>
        </div>
        <div>
          <h3 className="font-bold">{t("analysis.explainerMethodTitle")}</h3>
          <p>{t("analysis.explainerMethod")}</p>
        </div>
        <div>
          <h3 className="font-bold">{t("analysis.explainerLimitsTitle")}</h3>
          <p>{t("analysis.explainerLimits")}</p>
        </div>
      </div>
    </article>
  );
}

function Heatmap({
  metrics,
  lookup,
  correlations,
  onSelect,
}: {
  metrics: string[];
  lookup: Map<string, Correlation>;
  correlations: Correlation[];
  onSelect: (key: string) => void;
}) {
  const { t, locale, formatNumber } = useI18n();
  if (metrics.length < 2) return null;

  return (
    <article className="rounded-2xl border border-line bg-surface p-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-bold text-ink">
          {t("analysis.matrixTitle")}
        </h2>
        <HeatmapLegend />
      </div>
      <p className="mb-3 text-xs text-ink-muted">{t("analysis.matrixHint")}</p>

      <div className="hidden max-h-[32rem] overflow-auto rounded-xl border border-line md:block">
        <table
          className="min-w-max border-separate border-spacing-0 text-xs"
          aria-label={t("analysis.matrixAria")}
        >
          <caption className="sr-only">{t("analysis.matrixAria")}</caption>
          <thead>
            <tr>
              <th
                scope="col"
                className="sticky left-0 top-0 z-20 min-w-44 border-b border-r border-line bg-surface px-3 py-3 text-left font-semibold text-ink-muted"
              >
                {t("analysis.metricLabel")}
              </th>
              {metrics.map((metric) => (
                <th
                  key={metric}
                  scope="col"
                  className="sticky top-0 z-10 min-w-28 border-b border-line bg-surface px-2 py-3 text-center font-semibold text-ink-secondary"
                >
                  {metricLabel(metric, locale, true)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metrics.map((rowMetric, rowIndex) => (
              <tr key={rowMetric}>
                <th
                  scope="row"
                  className="sticky left-0 z-10 min-w-44 border-b border-r border-line bg-surface px-3 py-2 text-left font-semibold text-ink-secondary"
                >
                  {metricLabel(rowMetric, locale, true)}
                </th>
                {metrics.map((colMetric, colIndex) => {
                  const c =
                    colIndex > rowIndex ? lookup.get(rowMetric + "|" + colMetric) : undefined;
                  const key = rowMetric + "|" + colMetric;
                  return (
                    <td
                      key={colMetric}
                      className="border-b border-line p-1 text-center"
                    >
                      {c ? (
                        <button
                          type="button"
                          onClick={() => onSelect(key)}
                          className="flex min-h-14 w-full min-w-24 flex-col items-center justify-center rounded-lg px-1 py-1 text-xs font-semibold outline-none transition hover:ring-2 hover:ring-brand focus-visible:ring-2 focus-visible:ring-brand"
                          style={{
                            background: correlationColor(c.coefficient),
                            color: cellInk(c.coefficient),
                          }}
                          aria-label={t("analysis.matrixCellAria", {
                            first: metricLabel(rowMetric, locale, true),
                            second: metricLabel(colMetric, locale, true),
                            value: formatNumber(c.coefficient, {
                              maximumFractionDigits: 2,
                              signDisplay: "always",
                            }),
                          })}
                          title={t(
                            c.q_value === undefined
                              ? "analysis.matrixCellTitleRaw"
                              : "analysis.matrixCellTitle",
                            {
                              first: metricLabel(rowMetric, locale, true),
                              second: metricLabel(colMetric, locale, true),
                              value: formatNumber(c.coefficient, { maximumFractionDigits: 2 }),
                              q: formatNumber(c.q_value ?? c.p_value, {
                                maximumFractionDigits: 4,
                              }),
                            },
                          )}
                        >
                          <span>
                            {t("analysis.coefficientShort", {
                              value: formatNumber(c.coefficient, {
                                maximumFractionDigits: 2,
                                signDisplay: "always",
                              }),
                            })}
                          </span>
                          <span className="text-meta font-normal opacity-90">
                            {t(
                              c.q_value === undefined
                                ? "analysis.pValueShort"
                                : "analysis.qValueShort",
                              {
                                value: formatNumber(c.q_value ?? c.p_value, {
                                  maximumFractionDigits: 3,
                                }),
                              },
                            )}
                          </span>
                        </button>
                      ) : (
                        <span className="flex min-h-14 min-w-24 items-center justify-center rounded-lg bg-page text-ink-faint">
                          {rowIndex === colIndex ? "—" : colIndex < rowIndex ? "" : "·"}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-2 md:hidden">
        <p className="text-xs text-ink-muted">
          {t("analysis.matrixMobileHint")}
        </p>
        {correlations.map((correlation) => (
          <MatrixMobileCard
            key={correlation.metric_a + "|" + correlation.metric_b}
            correlation={correlation}
            onSelect={() => onSelect(correlation.metric_a + "|" + correlation.metric_b)}
          />
        ))}
      </div>
    </article>
  );
}

function MatrixMobileCard({
  correlation: c,
  onSelect,
}: {
  correlation: Correlation;
  onSelect: () => void;
}) {
  const { t, locale, formatNumber } = useI18n();
  return (
    <button
      type="button"
      onClick={onSelect}
      className="w-full rounded-xl border border-line bg-page p-3 text-left outline-none transition hover:border-brand focus-visible:ring-2 focus-visible:ring-brand"
      aria-label={t("analysis.matrixMobileAria", {
        first: metricLabel(c.metric_a, locale, true),
        second: metricLabel(c.metric_b, locale, true),
      })}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-ink-secondary">
          {metricLabel(c.metric_a, locale, true)} ↔ {metricLabel(c.metric_b, locale, true)}
        </span>
        <span
          className="rounded-md px-2 py-1 text-xs font-bold"
          style={{ background: correlationColor(c.coefficient), color: cellInk(c.coefficient) }}
        >
          {t("analysis.coefficientShort", {
            value: formatNumber(c.coefficient, {
              maximumFractionDigits: 2,
              signDisplay: "always",
            }),
          })}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-meta text-ink-muted">
        <span>{t("analysis.sharedDays", { count: formatNumber(c.sample_size) })}</span>
        <span>
          {t(c.q_value === undefined ? "analysis.pValueLabel" : "analysis.qValueLabel")}{" "}
          {formatNumber(c.q_value ?? c.p_value, { maximumFractionDigits: 4 })}
        </span>
      </div>
    </button>
  );
}

function TopFindings({ correlations }: { correlations: Correlation[] }) {
  const { t, locale, formatNumber } = useI18n();
  return (
    <div>
      <h2 className="mb-2 text-sm font-bold text-ink">
        {t("analysis.strongestTitle")}
      </h2>
      <div className="space-y-2">
        {correlations.map((c) => (
          <div
            key={`${c.metric_a}|${c.metric_b}`}
            className="rounded-2xl border border-line bg-surface p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold text-ink-secondary">
                {metricLabel(c.metric_a, locale, true)} ↔ {metricLabel(c.metric_b, locale, true)}
              </span>
              <span className="flex items-center gap-2 text-xs">
                <StrengthBar value={c.coefficient} />
                <span className="font-bold text-ink-secondary">
                  {c.direction === "positive"
                    ? t("analysis.sameDirection")
                    : t("analysis.oppositeDirection")}{" "}
                  {t("analysis.coefficientShort", {
                    value: formatNumber(c.coefficient, {
                      maximumFractionDigits: 2,
                      signDisplay: "always",
                    }),
                  })}
                </span>
              </span>
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">
              {interpretationText(
                t,
                c.interpretation_code,
                c.interpretation_params,
                c.interpretation,
                locale,
                formatNumber,
              )}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function CorrelationCard({
  correlation: c,
  provenance,
  quality,
}: {
  correlation: Correlation;
  provenance: Insights["provenance"];
  quality: Record<string, Quality>;
}) {
  const { t, locale, formatDate, formatDateTime, formatNumber } = useI18n();
  return (
    // Was a hand-rolled `useState` plus `aria-expanded` on a button plus a
    // manually rotated chevron — one of three spellings of "collapsible" in this
    // app. The shared component is a native `<details>`, so the expanded state is
    // announced by the element rather than by an attribute somebody remembered.
    <Disclosure
      id={correlationDomId(`${c.metric_a}|${c.metric_b}`)}
      className=""
      titleAs="h3"
      title={`${metricLabel(c.metric_a, locale, true)} ↔ ${metricLabel(c.metric_b, locale, true)}`}
      meta={
        <span className="flex items-center gap-2">
          <StrengthBar value={c.coefficient} />
          <span className="font-bold text-ink-secondary">
            {c.direction === "positive"
              ? t("analysis.sameDirection")
              : t("analysis.oppositeDirection")}{" "}
            {t("analysis.coefficientShort", {
              value: formatNumber(c.coefficient, {
                maximumFractionDigits: 2,
                signDisplay: "always",
              }),
            })}
          </span>
          {!c.significant && (
            <span className="rounded bg-surface-muted px-1.5 py-0.5 text-meta font-bold text-ink-muted">
              {t("analysis.notSignificant")}
            </span>
          )}
        </span>
      }
    >
      <div className="space-y-3 text-xs">
          <div>
            <h4 className="font-bold text-ink-secondary">
              {t("analysis.interpretationTitle")}
            </h4>
            <p className="mt-0.5 leading-relaxed text-ink-muted">
              {interpretationText(
                t,
                c.interpretation_code,
                c.interpretation_params,
                c.interpretation,
                locale,
                formatNumber,
              )}
            </p>
          </div>

          <div>
            <h4 className="font-bold text-ink-secondary">
              {t("analysis.provenanceTitle")}
            </h4>
            <ul className="mt-0.5 space-y-0.5 text-ink-muted">
              <li>{t("analysis.sharedDays", { count: formatNumber(c.sample_size) })}</li>
              <li>
                {t("analysis.periodLabel")} {formatDate(provenance.window_start)} –{" "}
                {formatDate(provenance.window_end)}
              </li>
              <li>{t("analysis.sources", { list: provenance.sources.join(", ") || "—" })}</li>
              <li>
                {t("analysis.coverageLabel")}{" "}
                {quality[c.metric_a]
                  ? formatNumber(quality[c.metric_a].coverage_pct, { maximumFractionDigits: 1 })
                  : "?"}{" "}
                % /{" "}
                {quality[c.metric_b]
                  ? formatNumber(quality[c.metric_b].coverage_pct, { maximumFractionDigits: 1 })
                  : "?"}{" "}
                %
              </li>
            </ul>
          </div>

          <div>
            <h4 className="font-bold text-ink-secondary">
              {t("analysis.calculationTitle")}
            </h4>
            <ul className="mt-0.5 space-y-0.5 text-ink-muted">
              <li>
                {t("analysis.pearsonLabel")} {formatNumber(c.pearson, { maximumFractionDigits: 3 })}
              </li>
              <li>
                {t("analysis.spearmanLabel")}{" "}
                {formatNumber(c.spearman, { maximumFractionDigits: 3 })}
              </li>
              <li>
                {t("analysis.pValueLabel")} {formatNumber(c.p_value, { maximumFractionDigits: 5 })}
                {c.q_value === undefined &&
                  ` — ${c.significant ? t("analysis.significant") : t("analysis.notSignificant")}`}
              </li>
              {c.q_value !== undefined && (
                <li>
                  {t("analysis.qValueLabel")}{" "}
                  {formatNumber(c.q_value, { maximumFractionDigits: 5 })} (
                  {t("analysis.bhAdjustment")}) —{" "}
                  {c.significant ? t("analysis.significant") : t("analysis.notSignificant")}
                </li>
              )}
              <li>
                {t("analysis.analysisVersionLabel")} {provenance.analysis_version ?? "—"}
              </li>
              <li>
                {t("analysis.computedLabel")} {formatDateTime(provenance.computed_at)}
              </li>
            </ul>
          </div>

          <div>
            <h4 className="font-bold text-ink-secondary">
              {t("analysis.limitsTitle")}
            </h4>
            <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-ink-muted">
              <li>{t("analysis.limitsBody")}</li>
              {c.caveat_codes
                ? c.caveat_codes.map((caveat, index) => {
                    const text =
                      correlationCaveatText(t, caveat, formatNumber) ?? c.caveats[index];
                    return text ? <li key={`${caveat.code}-${index}`}>{text}</li> : null;
                  })
                : c.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}
            </ul>
          </div>
      </div>
    </Disclosure>
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
      {/* A class, not a `stroke=` attribute: `var()` is not resolved in a
          presentation attribute, and the literal it replaces was the light
          theme's green drawn at 2.1:1 on the dark card. */}
      <path d={path} fill="none" className="stroke-brand" strokeWidth="2" />
    </svg>
  );
}

/**
 * The seven identifiers the Analysis Service sends, and their labels.
 *
 * A lookup rather than the templated cast `muscleKey` uses, because this value
 * can arrive from a *stored* report: a run computed before the server stopped
 * sending German words still holds `"Montag"`, and `t("weekday.Montag")` would
 * render that key as visible text. An unrecognised value falls back to the
 * server's own string — the posture rule 17 sets out for deployment warnings,
 * and here it means an old report stays readable until it is recomputed, which
 * happens on the next import or within twelve hours at the latest.
 */
const WEEKDAY_KEYS: Record<string, MessageKey> = {
  monday: "weekday.monday",
  tuesday: "weekday.tuesday",
  wednesday: "weekday.wednesday",
  thursday: "weekday.thursday",
  friday: "weekday.friday",
  saturday: "weekday.saturday",
  sunday: "weekday.sunday",
};

function WeekdayChart({
  data,
  metric,
  locale,
  formatNumber,
}: {
  data: { weekday: string; mean: number | null; sample_size: number }[];
  metric: string;
  locale: "de" | "en";
  formatNumber: NumberFormatter;
}) {
  const t = useT();
  const values = data.map((d) => d.mean).filter((v): v is number => v !== null);
  if (values.length === 0) return null;
  const max = Math.max(...values);

  return (
    <div className="space-y-1">
      {data.map((d) => (
        <div key={d.weekday} className="flex items-center gap-2 text-meta">
          <span className="w-20 shrink-0 text-ink-muted">
            {WEEKDAY_KEYS[d.weekday] ? t(WEEKDAY_KEYS[d.weekday]) : d.weekday}
          </span>
          <span className="h-3 flex-1 overflow-hidden rounded-sm bg-surface-muted">
            {d.mean !== null && (
              <span
                className="bg-brand block h-full rounded-sm"
                style={{ width: `${(d.mean / max) * 100}%` }}
              />
            )}
          </span>
          <span className="w-24 text-right text-ink-muted">
            {d.mean !== null ? metricValue(metric, d.mean, locale, formatNumber) : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

function Provenance({ provenance }: { provenance: Insights["provenance"] }) {
  const { t, formatDate, formatDateTime } = useI18n();
  return (
    <p className="text-meta text-ink-muted">
      {t("analysis.provenanceSummary", {
        start: formatDate(provenance.window_start),
        end: formatDate(provenance.window_end),
        sources: provenance.sources.join(", ") || "—",
        version: provenance.analysis_version ?? "—",
        computed: formatDateTime(provenance.computed_at),
      })}
    </p>
  );
}
