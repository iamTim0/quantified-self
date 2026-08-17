"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CircleAlert, Dumbbell, Info, Timer } from "lucide-react";
import { apiFetch } from "../lib/api";
import { plural, useI18n, type MessageKey } from "../lib/i18n/provider";
import { describeMetric } from "../lib/metrics/catalog";
import { LANE_LABEL } from "./DailyStory";

/**
 * Every session, newest first.
 *
 * A session is not a row anywhere — it is a group of points sharing a
 * `session_id`, or, for anything imported before that existed, a timestamp and a
 * title. The server does the grouping (`core.workouts`) and says which of the two
 * it used, because the difference matters to the reader: a `timestamp_title`
 * group can be two sessions merged or one split, and no amount of rendering can
 * recover the truth. So it is annotated rather than presented as certain.
 */

export interface WorkoutSummary {
  session_key: string;
  session_id: string | null;
  /** `session_id` or `timestamp_title` — an identifier, not prose (rule 17). */
  identity: string;
  start: string;
  end: string | null;
  title: string;
  category: string;
  source_id: string;
  measures: Record<string, number>;
  units: Record<string, string>;
  point_count: number;
  exercise_count: number;
  muscle_groups: string[];
}

interface WorkoutListResponse {
  sessions: WorkoutSummary[];
  scan_limit_reached: boolean;
  has_more: boolean;
}

const RANGES = [
  { days: 30, labelKey: "workouts.range30" },
  { days: 90, labelKey: "workouts.range90" },
  { days: 365, labelKey: "workouts.range365" },
] as const satisfies readonly { days: number; labelKey: MessageKey }[];

const CATEGORIES = [
  { value: "all", labelKey: "workouts.filterAll" },
  { value: "workout", labelKey: "workouts.filterWorkout" },
  { value: "strength", labelKey: "workouts.filterStrength" },
] as const satisfies readonly { value: string; labelKey: MessageKey }[];

/** Three measures is what fits a card without turning it into a table. */
const CARD_MEASURES = 3;

/**
 * How many sessions one request asks for.
 *
 * Named rather than inlined because the response's `has_more` is only
 * interpretable against it: "there are more" is a fact about this number.
 */
const SESSION_LIMIT = 100;

export function muscleKey(group: string): MessageKey {
  return `muscle.${group}` as MessageKey;
}

  /**
   * A real key, not a templated one.
   *
   * This read `t(\`day.category.${category}\`)`, and no such key exists in either
   * catalogue — the `as MessageKey` cast is what let it past `tsc`, and
   * `translate()` falls back to the key itself, so an untitled session rendered
   * the literal string `day.category.workout` as its heading. The lane labels are
   * the keys that exist, and they are imported rather than re-listed so the two
   * places cannot drift.
   */
export function categoryLabel(category: string): MessageKey {
  return LANE_LABEL[category] ?? "day.laneCustom";
}

/** The reader's own UTC offset in minutes, the way the daily story states it. */
function readerOffsetMinutes(): number {
  return -new Date().getTimezoneOffset();
}

/**
 * A calendar date in the reader's zone, `daysAgo` days back.
 *
 * `toISOString()` alone yields a *UTC* date, which paired with a local
 * `offset_minutes` asks the server a question about the wrong day: at UTC+2, one
 * o'clock in the morning is still yesterday in UTC, so `end_date` closed an hour
 * in the past and the day's sessions were simply absent.
 */
function localDate(daysAgo: number): string {
  const shifted = new Date(Date.now() + readerOffsetMinutes() * 60_000);
  shifted.setUTCDate(shifted.getUTCDate() - daysAgo);
  return shifted.toISOString().slice(0, 10);
}

/**
 * Which of the reader's days a session belongs to.
 *
 * `start.slice(0, 10)` is the UTC date of a UTC instant. West of UTC that files
 * an evening workout under tomorrow — an 8pm session at UTC-5 is `01:00Z` the next
 * day — and east of UTC it files a small-hours session under yesterday. The
 * request already states the reader's offset so the server's *window* is their
 * day; only the grouping was left in UTC.
 */
function localDayOf(instant: string): string {
  return new Date(
    new Date(instant).getTime() + readerOffsetMinutes() * 60_000,
  )
    .toISOString()
    .slice(0, 10);
}

interface Props {
  apiBase: string;
  onOpen: (sessionKey: string) => void;
  onUnauthorized: () => void;
}

export default function WorkoutsTab({ apiBase, onOpen, onUnauthorized }: Props) {
  const { t, locale, formatTime, formatDay, formatNumber } = useI18n();
  const [sessions, setSessions] = useState<WorkoutSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [truncated, setTruncated] = useState(false);
  // A second, different truncation. `scan_limit_reached` says the server stopped
  // scanning; `has_more` says the server found more than this request asked for.
  // Only the first had a banner, so a 365-day range holding 120 sessions showed
  // the newest 100 and looked complete — the oldest month simply was not there.
  const [hasMore, setHasMore] = useState(false);
  const [days, setDays] = useState<number>(30);
  const [category, setCategory] = useState<string>("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams({
        start_date: localDate(days),
        end_date: localDate(0),
        // The reader's own offset, so a session logged at 23:30 belongs to the
        // evening it happened in rather than to the following UTC day.
        offset_minutes: String(readerOffsetMinutes()),
        category,
        limit: String(SESSION_LIMIT),
      });
      const response = await apiFetch(`${apiBase}/api/v1/data/workouts?${query}`, {
        cache: "no-store",
      });
      if (response.status === 401) {
        onUnauthorized();
        return;
      }
      if (!response.ok) return;
      const body: WorkoutListResponse = await response.json();
      setSessions(body.sessions ?? []);
      setTruncated(Boolean(body.scan_limit_reached));
      setHasMore(Boolean(body.has_more));
    } finally {
      setLoading(false);
    }
  }, [apiBase, category, days, onUnauthorized]);

  useEffect(() => {
    void load();
  }, [load]);

  const byDay = useMemo(() => {
    const groups = new Map<string, WorkoutSummary[]>();
    for (const entry of sessions) {
      const day = localDayOf(entry.start);
      const bucket = groups.get(day);
      if (bucket) bucket.push(entry);
      else groups.set(day, [entry]);
    }
    return [...groups.entries()];
  }, [sessions]);

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h2 className="flex items-center gap-2 text-xl font-extrabold text-ink">
          <Dumbbell className="h-5 w-5 text-brand" />
          {t("workouts.title")}
        </h2>
        <p className="text-sm text-ink-muted">{t("workouts.subtitle")}</p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-xl border border-ok-line bg-ok-soft p-1 text-xs">
          {CATEGORIES.map((option) => (
            <button
              key={option.value}
              onClick={() => setCategory(option.value)}
              className={`min-h-9 rounded-lg px-3 py-1 font-semibold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
                category === option.value
                  ? "bg-brand text-brand-ink shadow-sm"
                  : "text-ok-ink hover:text-ok-ink"
              }`}
            >
              {t(option.labelKey)}
            </button>
          ))}
        </div>
        <div className="flex rounded-xl border border-line bg-page p-1 text-xs">
          {RANGES.map((option) => (
            <button
              key={option.days}
              onClick={() => setDays(option.days)}
              className={`min-h-9 rounded-lg px-3 py-1 font-semibold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
                days === option.days
                  ? "bg-slate-900 text-white shadow-sm"
                  : "text-ink-muted hover:text-ink"
              }`}
            >
              {t(option.labelKey)}
            </button>
          ))}
        </div>
      </div>

      {truncated && (
        <p className="flex items-start gap-2 rounded-2xl border border-warn-line bg-warn-soft p-3 text-xs text-warn-ink">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
          {t("workouts.scanTruncated")}
        </p>
      )}

      {hasMore && (
        <p className="flex items-start gap-2 rounded-2xl border border-line bg-page p-3 text-xs text-ink-secondary">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
          {t("workouts.listTruncated", { count: SESSION_LIMIT })}
        </p>
      )}

      {loading && sessions.length === 0 ? (
        <p className="rounded-3xl border border-line bg-surface p-6 text-sm text-ink-muted">
          {t("workouts.loading")}
        </p>
      ) : sessions.length === 0 ? (
        <div className="space-y-1 rounded-3xl border border-line bg-surface p-6">
          <p className="text-sm font-semibold text-ink-secondary">{t("workouts.empty")}</p>
          <p className="text-xs text-ink-muted">{t("workouts.emptyHint")}</p>
        </div>
      ) : (
        <div className="space-y-6">
          {byDay.map(([day, entries]) => (
            <section key={day} className="space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wide text-ink-muted">
                {/* `formatDay`, not `formatDate`: a date-only string parses as UTC
                    midnight and shows the previous day to any reader west of UTC. */}
                {formatDay(day)}
              </h3>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {entries.map((entry) => {
                  const measures = Object.entries(entry.measures).slice(0, CARD_MEASURES);
                  return (
                    <button
                      key={entry.session_key}
                      onClick={() => onOpen(entry.session_key)}
                      className="glass-card flex min-h-24 flex-col gap-2 rounded-2xl border border-line bg-surface p-4 text-left shadow-sm transition-shadow hover:shadow-md"
                    >
                      <div className="flex min-w-0 items-start justify-between gap-2">
                        <span className="truncate text-sm font-bold text-ink">
                          {entry.title || t(categoryLabel(entry.category))}
                        </span>
                        {/* `formatTime`, not the last five characters of a
                            localized datetime. `slice(-5)` assumed every locale
                            ends in `HH:MM` — true for German (`17.08.2026,
                            15:45`), false for English, whose 12-hour form ends
                            in `…5 PM`, so the card advertised `45 PM` as the
                            start of the session. */}
                        <span className="shrink-0 text-[11px] text-ink-muted">
                          {formatTime(entry.start)}
                        </span>
                      </div>

                      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-muted">
                        {measures.map(([metric, value]) => {
                          const described = describeMetric(metric, locale);
                          return (
                            <span key={metric} className="flex items-center gap-1">
                              <span className="font-semibold text-ink-secondary">
                                {formatNumber(value, {
                                  maximumFractionDigits: described.precision,
                                })}
                              </span>
                              <span className="text-ink-muted">
                                {described.unit || described.label}
                              </span>
                            </span>
                          );
                        })}
                      </div>

                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
                        {entry.exercise_count > 0 && (
                          <span className="flex items-center gap-1">
                            <Timer className="h-3 w-3" />
                            {t(
                              plural(
                                entry.exercise_count,
                                "workouts.exercises_one",
                                "workouts.exercises_other",
                              ),
                              { count: entry.exercise_count },
                            )}
                          </span>
                        )}
                        {entry.muscle_groups.map((group) => (
                          <span
                            key={group}
                            className="rounded-full bg-surface-muted px-2 py-0.5 text-ink-muted"
                          >
                            {t(muscleKey(group))}
                          </span>
                        ))}
                        {entry.identity === "timestamp_title" && (
                          <span
                            className="flex items-center gap-1 text-warn-ink"
                            title={t("workouts.approximateHint")}
                          >
                            <Info className="h-3 w-3" />
                            {t("workouts.approximate")}
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}