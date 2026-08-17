"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { CircleAlert, Clock, RefreshCw } from "lucide-react";
import { useI18n, type MessageKey } from "../lib/i18n/provider";
import { describeMetric } from "../lib/metrics/catalog";
import { useReport } from "../lib/reports";
import ReportStatus from "./ReportStatus";

const DayLocationMap = dynamic(() => import("./LocationMap"), {
  ssr: false,
  loading: () => (
    <div className="h-[420px] w-full rounded-3xl border border-slate-200 bg-slate-50" />
  ),
});

function DeferredDayLocationMap(props: {
  apiBase: string;
  day: string;
  offsetMinutes: number;
  refreshTrigger: number;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || visible) return;
    if (!("IntersectionObserver" in window)) {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "300px" },
    );
    observer.observe(host);
    return () => observer.disconnect();
  }, [visible]);

  return (
    <div ref={hostRef} className="min-h-[420px]" aria-busy={!visible}>
      {visible ? (
        <DayLocationMap {...props} />
      ) : (
        <div
          className="h-[420px] w-full animate-pulse rounded-3xl border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900"
          aria-hidden="true"
        />
      )}
    </div>
  );
}

/**
 * One day, told in the order it happened.
 *
 * This replaces a grid of cards showing whole-history averages — the mean of
 * every step count ever recorded, beside the mean of every sleep score ever
 * recorded. Those are real numbers that answer no question a person has in the
 * morning.
 *
 * **Today leads, yesterday follows.** The current day is the question most
 * readers ask first, even though it is partial by construction. Each lane says
 * when its connector last ran, so "no workout" and "the workout connector last
 * ran at 06:00" are distinguishable — which on the old page they were not.
 *
 * **Read from a stored run, not computed on arrival.** This page first fetched
 * both days on every visit, which meant aggregating a day of points — on a
 * workspace with per-minute sampling and a location trace, six figures of rows,
 * twice — for an answer that cannot change until an import does. It is a report
 * like the gap and conflict scans now: the reader sees the last good answer and
 * a note that newer data has arrived, rather than waiting for a scan.
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
  /** `only_source`, `preference` or `coverage` — an identifier, not prose (rule 17). */
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

type LoggedEntry = {
  title: string;
  metric_type: string;
  value: number | null;
  unit: string;
  /** The clock time the provider itself stated, where it stated one. */
  logged_at: string | null;
  amount: number | null;
  serving_unit: string | null;
};

/**
 * One meal of the day's log.
 *
 * Separate from `DayEvent` because these carry a day, not an hour. Yazio stamps a
 * whole day of food at that day's midnight UTC, which rendered in the reader's own
 * zone put every item at 02:00 — the same wrong hour for all of them, which reads
 * as a fact about the day rather than as an artefact of how a diary is stamped.
 */
type LoggedGroup = {
  /** `breakfast` | `lunch` | `dinner` | `snack` | … — an identifier, not prose. */
  group: string;
  category: string;
  entries: LoggedEntry[];
  entry_count: number;
  energy: number | null;
  /** True when the total is our sum of the items rather than the provider's own. */
  energy_derived: boolean;
  unit: string;
  logged_at: string | null;
};

export type DayStory = {
  day: string;
  /**
   * True when the server computed this run. Not read here — a report is
   * served while stale, so the client re-derives it from its own clock via
   * `relativeDay`. Kept because it is part of the wire shape.
   */
  is_today: boolean;
  complete: boolean;
  lanes: Lane[];
  events: DayEvent[];
  event_limit_reached: boolean;
  logged: LoggedGroup[];
  logged_limit_reached: boolean;
};

/**
 * Category identifiers the server sends, mapped to catalogue keys.
 *
 * Typed as `MessageKey`, not `string`: the whole point of the flat catalogue
 * is that a key which exists in neither language is a compile error rather
 * than an empty element at runtime.
 */
/**
 * Meal identifiers the server sends, mapped to catalogue keys.
 *
 * A group the server names but this map does not know keeps its own name rather
 * than disappearing — `meal_category` comes from the provider, so the set is not
 * ours to close.
 */
export const MEAL_LABEL: Record<string, MessageKey> = {
  breakfast: "day.mealBreakfast",
  lunch: "day.mealLunch",
  dinner: "day.mealDinner",
  snack: "day.mealSnack",
  other: "day.mealOther",
};

export const LANE_LABEL: Record<string, MessageKey> = {
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

/**
 * What a stored day is, relative to the reader's clock right now.
 *
 * Derived here rather than taken from the report, because a report is served
 * while it is stale. Between the reader's midnight and the recomputation that
 * follows it, the stored run still holds yesterday and the day before — correct
 * data under headings that would read "Yesterday" and "Today" and be wrong about
 * both. Reading the clock costs nothing and means the page is never wrong about
 * what it is showing, only sometimes behind — and behind is already on the label.
 */
function relativeDay(day: string, offsetMinutes: number): "today" | "yesterday" | "older" {
  const now = new Date(Date.now() + offsetMinutes * 60_000);
  const todayIso = now.toISOString().slice(0, 10);
  const yesterday = new Date(now.getTime() - 86_400_000).toISOString().slice(0, 10);
  if (day === todayIso) return "today";
  if (day === yesterday) return "yesterday";
  return "older";
}

/** Both days as one stored answer, which is what the run holds. */
type DayReport = {
  offset_minutes: number;
  days: DayStory[];
};

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

function DaySection({
  story,
  offsetMinutes,
  apiBase,
  refreshTrigger,
}: {
  story: DayStory;
  offsetMinutes: number;
  apiBase: string;
  refreshTrigger: number;
}) {
  const { t, formatDay, formatDateTime, formatTime, formatNumber, locale } = useI18n();
  const relative = relativeDay(story.day, offsetMinutes);
  // `older` gets no relative word at all: the date alone is honest, and
  // inventing "two days ago" for a report that is merely waiting to be
  // recomputed would tell the reader something about their data that is
  // really about the scheduler.
  const heading =
    relative === "today" ? t("day.today") : relative === "yesterday" ? t("day.yesterday") : "";

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
          {heading}{" "}
          <span className={heading ? "font-normal text-slate-400" : undefined}>
            {formatDay(story.day)}
          </span>
        </h2>
        {relative === "today" && (
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

      {story.lanes.some((lane) => lane.category === "location") && (
        <DeferredDayLocationMap
          apiBase={apiBase}
          day={story.day}
          offsetMinutes={offsetMinutes}
          refreshTrigger={refreshTrigger}
        />
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

      {story.logged.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <h3 className="mb-1 text-xs font-bold uppercase tracking-wider text-emerald-700">
            {t("day.logged")}
          </h3>
          {/* Says plainly why these carry no hour, so their absence from the
              timeline reads as a decision rather than as a gap. */}
          <p className="mb-3 text-xs text-slate-400">{t("day.loggedNote")}</p>
          <div className="space-y-3">
            {story.logged.map((group) => (
              <div key={group.group}>
                <div className="flex items-baseline justify-between gap-3">
                  <h4 className="text-sm font-semibold text-slate-800">
                    {MEAL_LABEL[group.group] ? t(MEAL_LABEL[group.group]) : group.group}
                  </h4>
                  {group.energy !== null && (
                    <span
                      className="shrink-0 text-sm font-semibold tabular-nums text-slate-900"
                      title={group.energy_derived ? t("day.loggedSummed") : undefined}
                    >
                      {formatNumber(group.energy)}{" "}
                      <span className="font-normal text-slate-400">
                        {group.unit}
                        {group.energy_derived && " *"}
                      </span>
                    </span>
                  )}
                </div>
                <ul className="mt-1 divide-y divide-slate-100">
                  {group.entries.map((entry, index) => (
                    <li
                      key={`${group.group}-${entry.title}-${index}`}
                      className="flex items-baseline justify-between gap-3 py-1 text-sm"
                    >
                      <span className="min-w-0 truncate text-slate-600">
                        {entry.logged_at && (
                          <span className="mr-2 tabular-nums text-slate-400">
                            {formatTime(entry.logged_at)}
                          </span>
                        )}
                        {entry.title}
                        {entry.amount !== null && (
                          <span className="ml-1.5 text-xs text-slate-400">
                            {formatNumber(entry.amount)} {entry.serving_unit ?? ""}
                          </span>
                        )}
                      </span>
                      <span className="shrink-0 tabular-nums text-slate-900">
                        {entry.value === null ? "—" : formatNumber(entry.value)}{" "}
                        <span className="font-normal text-slate-400">{entry.unit}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          {story.logged_limit_reached && (
            <p className="mt-3 text-xs text-slate-400">{t("day.loggedTruncated")}</p>
          )}
        </div>
      )}
    </section>
  );
}

export default function DailyStory({
  apiBase,
  refreshTrigger = 0,
}: {
  apiBase: string;
  refreshTrigger?: number;
}) {
  const { t } = useI18n();
  const report = useReport<DayReport>(apiBase, "day");

  // The reader's own offset, so a run computed for somebody else's midnight is
  // recomputed rather than shown. The server records it with the run.
  const offset = -new Date().getTimezoneOffset();
  const days = useMemo(() => {
    const rank = (story: DayStory): number => {
      const relative = relativeDay(story.day, offset);
      return relative === "today" ? 0 : relative === "yesterday" ? 1 : 2;
    };
    return [...(report.result?.days ?? [])].sort(
      (a, b) => rank(a) - rank(b) || b.day.localeCompare(a.day),
    );
  }, [offset, report.result?.days]);
  const requestFresh = () => void report.refresh({ offset_minutes: offset });

  if (report.loading) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-slate-500">
        <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-emerald-700">
            {t("day.eyebrow")}
          </p>
          <h1 className="text-3xl font-extrabold text-slate-900">{t("day.title")}</h1>
          <p className="mt-2 text-sm text-slate-500">{t("day.subtitle")}</p>
        </div>
        <ReportStatus
          computedAt={report.computed_at}
          stale={report.stale}
          running={report.running}
          neverComputed={report.status === "never_computed"}
          error={report.error}
          onRefresh={requestFresh}
        />
      </header>

      {report.status === "never_computed" && !report.running ? (
        <p className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600">
          {t("report.pendingFirstRun")}
        </p>
      ) : null}

      {days.map((story) => (
        <DaySection
          key={story.day}
          story={story}
          offsetMinutes={offset}
          apiBase={apiBase}
          refreshTrigger={refreshTrigger}
        />
      ))}
    </div>
  );
}
