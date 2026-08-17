"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { CircleAlert, Clock, RefreshCw } from "lucide-react";
import { plural, useI18n, type MessageKey } from "../lib/i18n/provider";
import { describeMetric } from "../lib/metrics/catalog";
import { useReport } from "../lib/reports";
import Disclosure from "./Disclosure";
import ReportStatus from "./ReportStatus";

/**
 * Leaflet and the day's trace, fetched only once the map section is opened.
 *
 * The `IntersectionObserver` wrapper that used to sit here is gone: the map now
 * lives in a `mountOnOpen` disclosure, so nothing renders until the reader asks
 * for it. That is both simpler and a stricter deferral than "within 300px of the
 * viewport" — and it is *required* rather than merely nicer, because Leaflet
 * sizes itself from its container and a container inside a closed `<details>`
 * has no box at all.
 */
const DayLocationMap = dynamic(() => import("./LocationMap"), {
  ssr: false,
  loading: () => (
    <div className="h-[420px] w-full rounded-3xl border border-line bg-page" />
  ),
});

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

/**
 * Category identifiers the server sends, mapped to catalogue keys.
 *
 * Typed as `MessageKey`, not `string`: the whole point of the flat catalogue
 * is that a key which exists in neither language is a compile error rather
 * than an empty element at runtime.
 */
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
  developer: "day.laneDeveloper",
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
      <span className="truncate text-body text-ink-muted">{described.label}</span>
      <span className="shrink-0 text-body font-semibold tabular-nums text-ink">
        {metric.value === null ? "—" : formatNumber(metric.value)}{" "}
        <span className="font-normal text-ink-muted">{described.unit}</span>
        {metric.other_sources.length > 0 && (
          // Named, because the reader is entitled to know that another connector
          // also reported this and was not added to it — and named *visibly*.
          // This was a `title`, which never fires on a touch device, so on a
          // phone the fact was simply absent. The lane repeats what the bracket
          // means once, below, rather than every row saying it.
          <span className="ml-1.5 text-xs font-normal text-ink-muted">
            ({metric.source_type ?? t("common.unknown")})
          </span>
        )}
      </span>
    </div>
  );
}

/**
 * The numbers a morning actually asks for, in the order they get a slot.
 *
 * Canonical registry keys, resolved against whatever the day happens to hold —
 * the first three that carry a value win. A day with fewer shows fewer; nothing
 * here invents a figure to fill a slot, because a headline is exactly where an
 * invented number would be believed.
 *
 * The list is a claim about what a person opens this page to find out, not about
 * what is most precisely measured.
 */
const HEADLINE_METRICS = [
  "sleep_duration",
  "steps",
  "nutrition_energy",
  "energy_active",
  "heart_rate_resting",
  "body_weight",
] as const;

const HEADLINE_SLOTS = 3;

/** The first lane holding this metric with an actual value. */
function findMetric(story: DayStory, metricType: string): LaneMetric | null {
  for (const lane of story.lanes) {
    const found = lane.metrics.find(
      (metric) => metric.metric_type === metricType && metric.value !== null,
    );
    if (found) return found;
  }
  return null;
}

function headlineMetrics(story: DayStory): LaneMetric[] {
  const picked: LaneMetric[] = [];
  for (const key of HEADLINE_METRICS) {
    if (picked.length >= HEADLINE_SLOTS) break;
    const metric = findMetric(story, key);
    if (metric) picked.push(metric);
  }
  return picked;
}

/**
 * The day in three numbers, with the previous day's for scale.
 *
 * The comparison costs nothing: the report already carries both days, because
 * both are what the page renders. It is deliberately unstyled by direction —
 * no green for "up", no red for "down". Whether more steps is good and more
 * body weight is bad is a judgement about a person's goals that this platform
 * does not hold, and colouring it in would state one anyway.
 */
function DayHeadline({ story, previous }: { story: DayStory; previous?: DayStory }) {
  const { t, formatNumber, locale } = useI18n();
  const picked = useMemo(() => headlineMetrics(story), [story]);
  if (picked.length === 0) return null;

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {picked.map((metric) => {
        const described = describeMetric(metric.metric_type, locale);
        const before = previous ? findMetric(previous, metric.metric_type) : null;
        const delta =
          before?.value != null && metric.value != null ? metric.value - before.value : null;
        return (
          <div
            key={metric.metric_type}
            className="rounded-2xl border border-line bg-surface p-4"
          >
            <p className="text-stat font-extrabold tabular-nums text-ink">
              {metric.value === null
                ? "—"
                : formatNumber(metric.value, { maximumFractionDigits: described.precision })}
              {described.unit && (
                <span className="ml-1 text-body font-semibold text-ink-muted">
                  {described.unit}
                </span>
              )}
            </p>
            <p className="text-meta font-semibold text-ink-secondary">{described.label}</p>
            {delta !== null && (
              <p className="mt-1 text-meta tabular-nums text-ink-muted">
                {formatNumber(delta, {
                  maximumFractionDigits: described.precision,
                  signDisplay: "always",
                })}{" "}
                {described.unit} {t("day.vsPreviousDay")}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function DaySection({
  story,
  previous,
  offsetMinutes,
  apiBase,
  refreshTrigger,
}: {
  story: DayStory;
  /** The day before this one, where the report carries it. Used only for scale. */
  previous?: DayStory;
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

  // One switch for the whole day, because the collapsed default is right for a
  // phone and expensive on a wide screen — six closed rows there is a click per
  // fact. The nonce remounts the disclosures so the new default takes effect;
  // making each one controlled from here would put the open state of every
  // section into this component for the sake of one button.
  const [expandAll, setExpandAll] = useState(false);
  const [expandNonce, setExpandNonce] = useState(0);
  const toggleAll = () => {
    setExpandAll((previousValue) => !previousValue);
    setExpandNonce((nonce) => nonce + 1);
  };

  const loggedTotal = story.logged.reduce((sum, group) => sum + (group.energy ?? 0), 0);
  const loggedUnit = story.logged.find((group) => group.energy !== null)?.unit ?? "";
  const hasMap = story.lanes.some((lane) => lane.category === "location");
  const hasSections =
    story.lanes.length > 0 || timeline.length > 0 || story.logged.length > 0 || hasMap;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-page font-bold text-ink">
          {heading}{" "}
          <span className={heading ? "font-normal text-ink-muted" : undefined}>
            {formatDay(story.day)}
          </span>
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          {relative === "today" && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-warn-soft px-2.5 py-0.5 text-meta font-medium text-warn-ink">
              <Clock className="h-3 w-3" aria-hidden="true" />
              {t("day.stillArriving")}
            </span>
          )}
          {hasSections && (
            <button
              type="button"
              onClick={toggleAll}
              className="min-h-11 rounded-xl px-2.5 text-meta font-semibold text-ink-muted hover:text-ink focus-ring"
            >
              {expandAll ? t("day.collapseAll") : t("day.expandAll")}
            </button>
          )}
        </div>
      </div>

      <DayHeadline story={story} previous={previous} />

      {story.lanes.length === 0 ? (
        <p className="rounded-2xl border border-line bg-surface p-5 text-body text-ink-muted">
          {t("day.nothingRecorded")}
        </p>
      ) : (
        <div className="space-y-2">
          {story.lanes.map((lane) => (
            <Disclosure
              key={`lane-${lane.category}-${expandNonce}`}
              defaultOpen={expandAll}
              titleAs="h3"
              title={t(LANE_LABEL[lane.category] ?? "day.laneOther")}
              meta={t(
                plural(lane.metrics.length, "day.valueCount_one", "day.valueCount_other"),
                { count: lane.metrics.length },
              )}
              /* The whole reason the lanes exist, and it has to survive being
                 collapsed. This file's doc comment says a lane distinguishes "no
                 workout" from "the workout connector last ran at 06:00"; that
                 distinction used to live in a `title` on an icon, which never
                 fires on touch, so on every phone the two states were one. */
              note={
                lane.complete ? undefined : (
                  <span className="flex items-start gap-1.5">
                    <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    <span>
                      {lane.last_import_at
                        ? t("day.lastImport", { timestamp: formatDateTime(lane.last_import_at) })
                        : t("day.neverImported")}
                    </span>
                  </span>
                )
              }
            >
              <div className="divide-y divide-line">
                {lane.metrics.map((metric) => (
                  <MetricValue key={metric.metric_type} metric={metric} />
                ))}
              </div>

              {lane.metrics.some((metric) => metric.other_sources.length > 0) && (
                <p className="mt-2 text-meta text-ink-muted">{t("day.multiSourceNote")}</p>
              )}
            </Disclosure>
          ))}

          {timeline.length > 0 && (
            <Disclosure
              key={`timeline-${expandNonce}`}
              defaultOpen={expandAll}
              titleAs="h3"
              title={t("day.timeline")}
              meta={t(plural(timeline.length, "day.eventCount_one", "day.eventCount_other"), {
                count: timeline.length,
              })}
            >
              <ol className="space-y-2">
                {timeline.map((event, index) => (
                  <li key={`${event.at}-${event.title}-${index}`} className="flex gap-3 text-body">
                    <span className="w-12 shrink-0 tabular-nums text-ink-muted">{event.clock}</span>
                    <span className="min-w-0 flex-1">
                      <span className="font-medium text-ink-secondary">
                        {event.title || t(LANE_LABEL[event.category] ?? "day.laneOther")}
                      </span>
                      <span className="ml-2 text-ink-muted">{event.detail}</span>
                    </span>
                  </li>
                ))}
              </ol>
              {story.event_limit_reached && (
                <p className="mt-3 text-meta text-ink-muted">{t("day.timelineTruncated")}</p>
              )}
            </Disclosure>
          )}

          {hasMap && (
            /* `mountOnOpen`: Leaflet sizes itself from its container, and a
               container inside a closed `<details>` has no box at all. This also
               replaces the IntersectionObserver that used to guess at intent from
               scroll position — being asked for is the more precise signal. */
            <Disclosure
              key={`map-${expandNonce}`}
              defaultOpen={expandAll}
              mountOnOpen
              titleAs="h3"
              title={t("day.mapSection")}
            >
              <DayLocationMap
                apiBase={apiBase}
                day={story.day}
                offsetMinutes={offsetMinutes}
                refreshTrigger={refreshTrigger}
              />
            </Disclosure>
          )}

          {story.logged.length > 0 && (
            <Disclosure
              key={`logged-${expandNonce}`}
              defaultOpen={expandAll}
              titleAs="h3"
              title={t("day.logged")}
              meta={
                loggedTotal > 0
                  ? `${formatNumber(loggedTotal)} ${loggedUnit}`.trim()
                  : t(plural(story.logged.length, "day.mealCount_one", "day.mealCount_other"), {
                      count: story.logged.length,
                    })
              }
            >
              {/* Says plainly why these carry no hour, so their absence from the
                  timeline reads as a decision rather than as a gap. */}
              <p className="mb-3 text-meta text-ink-muted">{t("day.loggedNote")}</p>
              <div className="space-y-3">
                {story.logged.map((group) => (
                  <div key={group.group}>
                    <div className="flex items-baseline justify-between gap-3">
                      <h4 className="text-body font-semibold text-ink-secondary">
                        {MEAL_LABEL[group.group] ? t(MEAL_LABEL[group.group]) : group.group}
                      </h4>
                      {group.energy !== null && (
                        <span className="shrink-0 text-body font-semibold tabular-nums text-ink">
                          {formatNumber(group.energy)}{" "}
                          <span className="font-normal text-ink-muted">{group.unit}</span>
                        </span>
                      )}
                    </div>

                    {/* Was a bare `*` whose meaning was a `title`. A derived number
                        that does not visibly say it was derived is exactly what rule
                        19 exists to prevent, and the asterisk carried that duty on
                        hover only — which is to say, not on a phone at all. */}
                    {group.energy !== null && group.energy_derived && (
                      <p className="text-meta text-ink-muted">{t("day.loggedSummed")}</p>
                    )}
                    <ul className="mt-1 divide-y divide-line">
                      {group.entries.map((entry, index) => (
                        <li
                          key={`${group.group}-${entry.title}-${index}`}
                          className="flex items-baseline justify-between gap-3 py-1 text-body"
                        >
                          <span className="min-w-0 truncate text-ink-muted">
                            {entry.logged_at && (
                              <span className="mr-2 tabular-nums text-ink-muted">
                                {formatTime(entry.logged_at)}
                              </span>
                            )}
                            {entry.title}
                            {entry.amount !== null && (
                              <span className="ml-1.5 text-meta text-ink-muted">
                                {formatNumber(entry.amount)} {entry.serving_unit ?? ""}
                              </span>
                            )}
                          </span>
                          <span className="shrink-0 tabular-nums text-ink">
                            {entry.value === null ? "—" : formatNumber(entry.value)}{" "}
                            <span className="font-normal text-ink-muted">{entry.unit}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
              {story.logged_limit_reached && (
                <p className="mt-3 text-meta text-ink-muted">{t("day.loggedTruncated")}</p>
              )}
            </Disclosure>
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
      <div className="flex items-center gap-2 p-6 text-sm text-ink-muted">
        <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-ok-ink">
            {t("day.eyebrow")}
          </p>
          <h1 className="text-3xl font-extrabold text-ink">{t("day.title")}</h1>
          <p className="mt-2 text-sm text-ink-muted">{t("day.subtitle")}</p>
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
        <p className="rounded-2xl border border-line bg-surface p-5 text-sm text-ink-muted">
          {t("report.pendingFirstRun")}
        </p>
      ) : null}

      {days.map((story, index) => (
        <DaySection
          key={story.day}
          story={story}
          // `days` is sorted newest first, so the next entry is the day before.
          // Only used for the headline's comparison; the last day simply has none.
          previous={days[index + 1]}
          offsetMinutes={offset}
          apiBase={apiBase}
          refreshTrigger={refreshTrigger}
        />
      ))}
    </div>
  );
}
