"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CircleAlert, Clock, RefreshCw } from "lucide-react";
import { apiFetch } from "../lib/api";
import { useI18n, type MessageKey } from "../lib/i18n/provider";
import { describeMetric } from "../lib/metrics/catalog";

/**
 * One day, told in the order it happened.
 *
 * This replaces a grid of cards showing whole-history averages — the mean of
 * every step count ever recorded, beside the mean of every sleep score ever
 * recorded. Those are real numbers that answer no question a person has in the
 * morning.
 *
 * **Yesterday leads, today follows.** Yesterday is a finished day whose
 * importers have run; today is partial by construction, because the connectors
 * feeding it are on a schedule. Showing today first would put the least complete
 * data at the top and invite every gap to be read as a fact. Each lane says when
 * its connector last ran, so "no workout" and "the workout connector last ran at
 * 06:00" are distinguishable — which on the old page they were not.
 */

type LaneMetric = {
  metric_type: string;
  value: number | null;
  unit: string;
  aggregation: string;
  cadence: string;
  sample_count: number;
  source_id: string;
  source_type: string | null;
  /** ONLY_SOURCE, PREFERENCE or COVERAGE — an identifier, not prose (rule 17). */
  source_reason: string;
  other_sources: string[];
  last_at: string | null;
};

type Lane = {
  category: string;
  metrics: LaneMetric[];
  last_import_at: string | null;
  complete: boolean;
};

type DayEvent = {
  at: string;
  until?: string;
  title: string;
  category: string;
  source_id: string;
  measures: Record<string, number>;
};

export type DayStory = {
  day: string;
  is_today: boolean;
  complete: boolean;
  lanes: Lane[];
  events: DayEvent[];
  event_limit_reached: boolean;
};

/**
 * Category identifiers the server sends, mapped to catalogue keys.
 *
 * Typed as `MessageKey`, not `string`: the whole point of the flat catalogue
 * is that a key which exists in neither language is a compile error rather
 * than an empty element at runtime.
 */
const LANE_LABEL: Record<string, MessageKey> = {
  sleep: "day.laneSleep",
  activity: "day.laneActivity",
  workout: "day.laneWorkout",
  strength: "day.laneStrength",
  heart: "day.laneHeart",
  nutrition: "day.laneNutrition",
  body: "day.laneBody",
  location: "day.laneLocation",
  calendar: "day.laneCalendar",
  environment: "day.laneEnvironment",
  home: "day.laneHome",
  custom: "day.laneCustom",
};

function useDay(
  apiBase: string,
  dayOffset: number,
  refreshTrigger: number,
  onUnauthorized: () => void,
) {
  const [story, setStory] = useState<DayStory | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const target = new Date();
    target.setDate(target.getDate() - dayOffset);
    const iso = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}-${String(
      target.getDate(),
    ).padStart(2, "0")}`;
    // The reader's own offset. Day rollups are bucketed in UTC, so without this
    // a reader two hours east is shown a day running 22:00 to 22:00.
    const offset = -new Date().getTimezoneOffset();
    try {
      const response = await apiFetch(
        `${apiBase}/api/v1/data/day?day=${iso}&offset_minutes=${offset}`,
      );
      // A 401 that survived `apiFetch`'s own refresh means the session is over.
      // Swallowing it left a permanently blank page where the previous overview
      // signed the reader out.
      if (response.status === 401) {
        onUnauthorized();
        return;
      }
      if (response.ok) setStory((await response.json()) as DayStory);
    } catch {
      // Left as it was; the next visit re-reads.
    } finally {
      setLoading(false);
    }
  }, [apiBase, dayOffset, onUnauthorized]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) await load();
    })();
    return () => {
      cancelled = true;
    };
    // `refreshTrigger` belongs here: the shell bumps it when the tab becomes
    // visible again and after a sync finishes. Without it the one page whose
    // premise is "today, as far as importers have reported" was frozen at mount.
  }, [load, refreshTrigger]);

  return { story, loading, reload: load };
}

function MetricValue({ metric }: { metric: LaneMetric }) {
  const { t, formatNumber, locale } = useI18n();
  const described = describeMetric(metric.metric_type, locale);
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="truncate text-sm text-slate-600">{described.label}</span>
      <span className="shrink-0 text-sm font-semibold tabular-nums text-slate-900">
        {metric.value === null ? "—" : formatNumber(metric.value)}{" "}
        <span className="font-normal text-slate-400">{described.unit}</span>
        {metric.other_sources.length > 0 && (
          // Named, because the reader is entitled to know that another connector
          // also reported this and was not added to it.
          <span
            className="ml-1.5 cursor-help text-xs font-normal text-slate-400"
            title={t("day.answeredBy", { source: metric.source_type ?? metric.source_id })}
          >
            ({metric.source_type ?? "?"})
          </span>
        )}
      </span>
    </div>
  );
}

function DaySection({ story, heading }: { story: DayStory; heading: string }) {
  const { t, formatDay, formatDateTime, formatTime, formatNumber, locale } = useI18n();

  const timeline = useMemo(
    () =>
      story.events.map((event) => ({
        ...event,
        clock: formatTime(event.at),
        // Formatted with its unit, like every other number on this page. Raw
        // `610` beside "Running" says less than "Energy: 610 kcal", and the
        // registry already knows both the label and the unit.
        detail: Object.entries(event.measures)
          .slice(0, 3)
          .map(([key, value]) => {
            const described = describeMetric(key, locale);
            return `${described.label}: ${formatNumber(value)} ${described.unit}`.trim();
          })
          .join(" · "),
      })),
    [story.events, formatTime, formatNumber, locale],
  );

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-bold text-slate-900">
          {heading} <span className="font-normal text-slate-400">{formatDay(story.day)}</span>
        </h2>
        {story.is_today && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">
            <Clock className="h-3 w-3" aria-hidden="true" />
            {t("day.stillArriving")}
          </span>
        )}
      </div>

      {story.lanes.length === 0 ? (
        <p className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-400">
          {t("day.nothingRecorded")}
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {story.lanes.map((lane) => (
            <article
              key={lane.category}
              className="rounded-2xl border border-slate-200 bg-white p-4"
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-700">
                  {t(LANE_LABEL[lane.category] ?? "day.laneOther")}
                </h3>
                {!lane.complete && (
                  <span
                    className="text-slate-400"
                    title={
                      lane.last_import_at
                        ? t("day.lastImport", { timestamp: formatDateTime(lane.last_import_at) })
                        : t("day.neverImported")
                    }
                  >
                    <CircleAlert className="h-3.5 w-3.5" aria-hidden="true" />
                  </span>
                )}
              </div>
              <div className="divide-y divide-slate-100">
                {lane.metrics.map((metric) => (
                  <MetricValue key={metric.metric_type} metric={metric} />
                ))}
              </div>
            </article>
          ))}
        </div>
      )}

      {timeline.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-emerald-700">
            {t("day.timeline")}
          </h3>
          <ol className="space-y-2">
            {timeline.map((event, index) => (
              <li key={`${event.at}-${event.title}-${index}`} className="flex gap-3 text-sm">
                <span className="w-12 shrink-0 tabular-nums text-slate-400">{event.clock}</span>
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-slate-800">
                    {event.title || t(LANE_LABEL[event.category] ?? "day.laneOther")}
                  </span>
                  <span className="ml-2 text-slate-500">{event.detail}</span>
                </span>
              </li>
            ))}
          </ol>
          {story.event_limit_reached && (
            <p className="mt-3 text-xs text-slate-400">{t("day.timelineTruncated")}</p>
          )}
        </div>
      )}
    </section>
  );
}

export default function DailyStory({
  apiBase,
  refreshTrigger = 0,
  onUnauthorized,
}: {
  apiBase: string;
  refreshTrigger?: number;
  onUnauthorized: () => void;
}) {
  const { t } = useI18n();
  // Yesterday first: it is the finished day. Today is partial by construction,
  // and leading with it puts the least complete data at the top.
  const yesterday = useDay(apiBase, 1, refreshTrigger, onUnauthorized);
  const today = useDay(apiBase, 0, refreshTrigger, onUnauthorized);

  if (yesterday.loading && today.loading) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-slate-500">
        <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <header>
        <p className="text-xs font-bold uppercase tracking-widest text-emerald-700">
          {t("day.eyebrow")}
        </p>
        <h1 className="text-3xl font-extrabold text-slate-900">{t("day.title")}</h1>
        <p className="mt-2 text-sm text-slate-500">{t("day.subtitle")}</p>
      </header>

      {yesterday.story && <DaySection story={yesterday.story} heading={t("day.yesterday")} />}
      {today.story && <DaySection story={today.story} heading={t("day.today")} />}
    </div>
  );
}
