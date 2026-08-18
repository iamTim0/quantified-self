"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { ArrowLeft, CircleAlert, Info, MapPin } from "lucide-react";
import { apiFetch } from "../lib/api";
import { plural, useI18n } from "../lib/i18n/provider";
import { describeMetric } from "../lib/metrics/catalog";
import StreamChart from "./StreamChart";
import { categoryLabel, muscleKey } from "./WorkoutsTab";
import type { GpsPoint } from "./LocationMap";

/**
 * One session, and every reading any connector took while it was happening.
 *
 * The last part is the point of the page. The weather connector and the sleep
 * tracker know nothing about a workout; they appear because their readings fall
 * inside its span, which is what "during my workout" means. The server resolves
 * that span and answers with aggregates rather than rows, so a three-hour ride
 * costs the same as a twenty-minute run.
 *
 * Leaflet stays behind the map component's own opt-in — nothing here loads a tile
 * without being asked.
 */

const LocationMap = dynamic(() => import("./LocationMap"), {
  ssr: false,
  loading: () => <div className="h-[420px] w-full rounded-3xl border border-line bg-page" />,
});

interface Measure {
  metric_type: string;
  value: number;
  unit: string;
  aggregation: string;
  category: string;
  provider_value: number | null;
  units: string | null;
  derived_by: string | null;
  derived_from: string[] | null;
  sample_count: number;
  source_id: string;
}

interface StrengthSet {
  set_number: number | null;
  at: string;
  weight?: number;
  reps?: number;
  volume?: number;
  heart_rate_max?: number;
  notes: string | null;
}

interface Exercise {
  exercise_title: string;
  muscle_group: string | null;
  exercise_category: string | null;
  sets: StrengthSet[];
  total_volume: number;
  total_reps: number;
  top_set_weight: number | null;
}

export interface StreamPoint {
  t: string;
  avg: number | null;
  min: number | null;
  max: number | null;
  n: number;
}

interface Stream {
  metric_type: string;
  source_id: string;
  unit: string;
  bucket_seconds: number;
  points: StreamPoint[];
  point_count: number;
  truncated: boolean;
}

interface Route {
  source: string;
  measured_distance_m: number | null;
  fix_count: number;
  samples: { t: string; lat: number; lon: number; altitude: number | null; speed: number | null }[];
  sample_count: number;
  truncated: boolean;
}

interface Surrounding {
  metric_type: string;
  value: number | null;
  unit: string;
  category: string;
  source_type: string | null;
  /** `only_source`, `preference` or `coverage` — an identifier, not prose (rule 17). */
  source_reason: string;
  other_sources: string[];
  sample_count: number;
}

interface WorkoutDetailBody {
  session_key: string;
  identity: string;
  title: string;
  category: string;
  context: Record<string, unknown>;
  window: { start: string; end: string; clamped: boolean };
  measures: Measure[];
  strength: {
    exercises: Exercise[];
    total_volume: number;
    total_sets: number;
    set_rows_truncated: boolean;
  };
  streams: Stream[];
  route: Route | null;
  surroundings: Surrounding[];
}

interface Props {
  apiBase: string;
  sessionKey: string;
  onBack: () => void;
  onUnauthorized: () => void;
}

export default function WorkoutDetail({ apiBase, sessionKey, onBack, onUnauthorized }: Props) {
  const { t, locale, formatDateTime, formatNumber } = useI18n();
  // From the registry, not spelled out: `strength_set_weight` declares its unit
  // in one place, and a second copy here is one a unit change would leave behind.
  const weightUnit = describeMetric("strength_set_weight", locale).unit;
  const volumeUnit = describeMetric("strength_set_volume", locale).unit;
  const distanceUnit = describeMetric("workout_distance", locale).unit;
  const [body, setBody] = useState<WorkoutDetailBody | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setMissing(false);
    try {
      const response = await apiFetch(
        `${apiBase}/api/v1/data/workouts/${encodeURIComponent(sessionKey)}`,
        { cache: "no-store" },
      );
      if (response.status === 401) {
        onUnauthorized();
        return;
      }
      if (response.status === 404 || response.status === 400) {
        setMissing(true);
        return;
      }
      if (!response.ok) return;
      setBody(await response.json());
    } finally {
      setLoading(false);
    }
  }, [apiBase, sessionKey, onUnauthorized]);

  useEffect(() => {
    void load();
  }, [load]);

  const back = (
    <button
      onClick={onBack}
      className="flex min-h-9 items-center gap-1.5 text-xs font-semibold text-ink-muted hover:text-ink"
    >
      <ArrowLeft className="h-4 w-4" />
      {t("workouts.back")}
    </button>
  );

  if (loading && !body) {
    return (
      <div className="space-y-4">
        {back}
        <p className="rounded-3xl border border-line bg-surface p-6 text-sm text-ink-muted">
          {t("workouts.loading")}
        </p>
      </div>
    );
  }

  if (missing || !body) {
    return (
      <div className="space-y-4">
        {back}
        <p className="rounded-3xl border border-line bg-surface p-6 text-sm text-ink-muted">
          {t("workouts.notFound")}
        </p>
      </div>
    );
  }

  // The map takes the fixes the endpoint already decimated. Passing them keeps it
  // from re-fetching a calendar day and drawing a different route from the one the
  // session actually resolved to.
  const routePoints: GpsPoint[] = (body.route?.samples ?? []).map((fix) => ({
    latitude: fix.lat,
    longitude: fix.lon,
    timestamp: fix.t,
    altitude: fix.altitude ?? undefined,
    speed: fix.speed ?? undefined,
  }));

  return (
    <div className="space-y-6">
      {back}

      <header className="space-y-1">
        <h2 className="text-xl font-extrabold text-ink">
          {body.title || t(categoryLabel(body.category))}
        </h2>
        <p className="text-sm text-ink-muted">
          {formatDateTime(body.window.start)} – {formatDateTime(body.window.end)}
        </p>
        {body.identity === "timestamp_title" && (
          <p className="flex items-start gap-2 pt-1 text-xs text-warn-ink">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {t("workouts.approximateHint")}
          </p>
        )}
        {body.window.clamped && (
          <p className="flex items-start gap-2 pt-1 text-xs text-warn-ink">
            <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {t("workouts.clamped")}
          </p>
        )}
      </header>

      {/* What the session states about itself */}
      <section className="space-y-2">
        <h3 className="text-xs font-bold uppercase tracking-wide text-ink-muted">
          {t("workouts.measures")}
        </h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {body.measures.map((measure) => {
            const described = describeMetric(measure.metric_type, locale);
            return (
              <div
                key={measure.metric_type}
                className="glass-card rounded-2xl border border-line bg-surface p-4 shadow-sm"
              >
                <p className="text-meta font-semibold uppercase tracking-wide text-ink-muted">
                  {described.label}
                </p>
                <p className="mt-1 text-lg font-extrabold text-ink">
                  {formatNumber(measure.value, {
                    maximumFractionDigits: described.precision,
                  })}{" "}
                  <span className="text-xs font-semibold text-ink-muted">{measure.unit}</span>
                </p>
                {measure.derived_by && measure.derived_from && (
                  <p className="mt-1 text-meta text-ink-muted">
                    {t("workouts.derived", { fields: measure.derived_from.join(", ") })}
                  </p>
                )}
                {measure.provider_value !== null && measure.units && (
                  <p className="mt-0.5 text-meta text-ink-muted">
                    {t("workouts.providerValue", {
                      value: formatNumber(measure.provider_value, {
                        maximumFractionDigits: 3,
                      }),
                      unit: measure.units,
                    })}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* The route */}
      {body.route && routePoints.length > 0 && (
        <section className="space-y-2">
          <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-ink-muted">
            <MapPin className="h-3.5 w-3.5" />
            {t("workouts.route")}
          </h3>
          <LocationMap points={routePoints} showHeader={false} />
          <p className="flex flex-wrap gap-x-3 text-meta text-ink-muted">
            <span>
              {t(
                plural(
                  body.route.fix_count,
                  "workouts.routeFixes_one",
                  "workouts.routeFixes_other",
                ),
                { count: formatNumber(body.route.fix_count) },
              )}
            </span>
            {body.route.measured_distance_m !== null && (
              <span>
                {t("workouts.routeMeasured", {
                  distance: `${formatNumber(body.route.measured_distance_m / 1000, {
                    maximumFractionDigits: 2,
                  })} ${distanceUnit}`,
                })}
              </span>
            )}
            {body.route.source === "metadata" && <span>{t("workouts.routeFallback")}</span>}
          </p>
        </section>
      )}

      {/* Series recorded inside the session */}
      <section className="space-y-2">
        <h3 className="text-xs font-bold uppercase tracking-wide text-ink-muted">
          {t("workouts.streams")}
        </h3>
        {body.streams.length === 0 ? (
          <p className="rounded-2xl border border-line bg-surface p-4 text-xs text-ink-muted">
            {t("workouts.noStreams")}
          </p>
        ) : (
          <div className="space-y-4">
            {body.streams.map((stream) => (
              <StreamChart
                key={`${stream.metric_type}-${stream.source_id}`}
                metricType={stream.metric_type}
                unit={stream.unit}
                bucketSeconds={stream.bucket_seconds}
                points={stream.points}
                truncated={stream.truncated}
              />
            ))}
          </div>
        )}
      </section>

      {/* Sets, grouped by exercise */}
      {body.strength.exercises.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wide text-ink-muted">
            {t("workouts.strength")}
          </h3>
          {body.strength.set_rows_truncated && (
            <p className="text-meta text-warn-ink">{t("workouts.strengthTruncated")}</p>
          )}
          <div className="space-y-3">
            {body.strength.exercises.map((exercise) => (
              <div
                key={exercise.exercise_title}
                className="glass-card overflow-hidden rounded-2xl border border-line bg-surface shadow-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-4">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-sm font-bold text-ink">
                      {exercise.exercise_title}
                    </span>
                    {exercise.muscle_group && (
                      <span
                        className="rounded-full bg-surface-muted px-2 py-0.5 text-meta text-ink-muted"
                        title={exercise.exercise_category ?? undefined}
                      >
                        {t(muscleKey(exercise.muscle_group))}
                      </span>
                    )}
                  </div>
                  <div className="flex gap-3 text-meta text-ink-muted">
                    {exercise.top_set_weight !== null && (
                      <span>
                        {t("workouts.topSet")}:{" "}
                        <b className="text-ink-secondary">
                          {formatNumber(exercise.top_set_weight, {
                            maximumFractionDigits: 1,
                          })}{" "}
                          {weightUnit}
                        </b>
                      </span>
                    )}
                    <span>
                      {t("workouts.totalVolume")}:{" "}
                      <b className="text-ink-secondary">
                        {formatNumber(exercise.total_volume, { maximumFractionDigits: 0 })}{" "}
                        {volumeUnit}
                      </b>
                    </span>
                    <span>
                      {t("workouts.totalReps")}:{" "}
                      <b className="text-ink-secondary">{formatNumber(exercise.total_reps)}</b>
                    </span>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[420px] text-left text-xs">
                    <thead className="text-meta uppercase tracking-wide text-ink-muted">
                      <tr>
                        <th className="px-4 py-2 font-semibold">{t("workouts.setNumber")}</th>
                        <th className="px-4 py-2 font-semibold">{t("workouts.weight")}</th>
                        <th className="px-4 py-2 font-semibold">{t("workouts.reps")}</th>
                        <th className="px-4 py-2 font-semibold">{t("workouts.volume")}</th>
                      </tr>
                    </thead>
                    <tbody className="text-ink-secondary">
                      {exercise.sets.map((set, index) => (
                        <tr key={`${set.at}-${index}`} className="border-t border-line">
                          <td className="px-4 py-2 text-ink-muted">
                            {set.set_number ?? index + 1}
                          </td>
                          <td className="px-4 py-2 font-semibold">
                            {set.weight === undefined
                              ? "—"
                              : `${formatNumber(set.weight, {
                                  maximumFractionDigits: 1,
                                })} ${weightUnit}`}
                          </td>
                          <td className="px-4 py-2">{set.reps ?? "—"}</td>
                          <td className="px-4 py-2 text-ink-muted">
                            {set.volume === undefined
                              ? "—"
                              : `${formatNumber(set.volume, {
                                  maximumFractionDigits: 0,
                                })} ${volumeUnit}`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Everything else recorded in the same window */}
      {body.surroundings.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wide text-ink-muted">
            {t("workouts.surroundings")}
          </h3>
          <p className="text-meta text-ink-muted">{t("workouts.surroundingsHint")}</p>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {body.surroundings.map((row) => {
              const described = describeMetric(row.metric_type, locale);
              return (
                <div
                  key={`${row.metric_type}-${row.source_type}`}
                  className="flex items-baseline justify-between gap-2 rounded-2xl border border-line bg-surface px-4 py-3"
                >
                  <span className="min-w-0 truncate text-xs text-ink-muted">
                    {described.label}
                  </span>
                  <span className="shrink-0 text-sm font-bold text-ink">
                    {row.value === null
                      ? "—"
                      : formatNumber(row.value, {
                          maximumFractionDigits: described.precision,
                        })}{" "}
                    <span className="text-meta font-semibold text-ink-muted">{row.unit}</span>
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
