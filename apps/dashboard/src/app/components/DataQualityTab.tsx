"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, BookOpen, CalendarX2, Lightbulb, RefreshCw } from "lucide-react";
import ImportDialog from "./ImportDialog";
import ReportStatus from "./ReportStatus";
import { plural, useI18n, type Translate } from "../lib/i18n/provider";
import { apiFetch } from "../lib/api";
import { usePolling } from "../lib/polling";
import { useReport } from "../lib/reports";
import { describeMetric } from "../lib/metrics/catalog";

// tenantId is no longer read: Core derives the tenant from the session credential, so the
// prop is kept only for call-site compatibility with the other tabs.
type Props = { apiBase: string; tenantId?: string };
type Gap = { metric_type: string; missing_dates: string[] };
type Connector = {
  source_id: string;
  source_type: string;
  display_name?: string;
  lookback_days: number;
  lookback_hours?: number;
};

/**
 * An interruption in a metric sampled faster than daily.
 *
 * Reported as spans rather than missing days: a calendar day is the wrong unit
 * for something recorded every few minutes. Without reading these, heart rate and
 * every weather series would show nothing at all once they left the daily check.
 */
type CadenceGap = {
  metric_type: string;
  missing_ranges: { start: string; end: string }[];
};

/** The stored result of a scheduled gap run. */
type GapReport = {
  gaps: Gap[];
  cadence_gaps: CadenceGap[];
  missing_count: number;
};

/**
 * One connector's reading inside a disagreement.
 *
 * `source_id` is the connector *instance*, which is what makes two rows of the
 * same `source_type` distinguishable — two Apple Health connectors can disagree
 * with each other.
 */
type ConflictCandidate = {
  id: string;
  source_id: string;
  metric_type: string;
  timestamp: string;
  value: number | null;
};

/** Same metric, same day, values from different connectors beyond the tolerance. */
type Conflict = {
  metric_type: string;
  date: string;
  candidates: ConflictCandidate[];
};

/**
 * The stored result of a scheduled cross-source conflict run.
 *
 * This was `unknown[]`, and only `.length` was ever read — so the page stated a
 * count and gave advice about items it had no way to show. A number the reader
 * cannot investigate is an accusation, not a finding; the shape is written out
 * here because `core.analytics.find_cross_source_conflicts` has always sent it.
 */
type ConflictReport = {
  conflicts: Conflict[];
};

/** How many disagreements the list shows before it says how many it is hiding. */
const CONFLICTS_SHOWN = 6;

/**
 * A connector instance's readable name.
 *
 * Falls back to the raw `source_id`, not to a placeholder: a connector can be
 * deleted while the points it wrote remain, and "unknown" in both rows of a
 * disagreement would make the two readings indistinguishable — which is the one
 * thing this list exists to do.
 */
function connectorLabel(connectors: Connector[], sourceId: string): string {
  const match = connectors.find((connector) => connector.source_id === sourceId);
  return match?.display_name?.trim() || match?.source_type || sourceId;
}

/** Contiguous runs of missing days, so "12 days" becomes a usable backfill range. */
function toRanges(dates: string[]): { start: string; end: string; days: number }[] {
  const sorted = [...dates].sort();
  const ranges: { start: string; end: string; days: number }[] = [];

  for (const day of sorted) {
    const last = ranges[ranges.length - 1];
    if (last) {
      const nextExpected = new Date(`${last.end}T00:00:00Z`);
      nextExpected.setUTCDate(nextExpected.getUTCDate() + 1);
      if (nextExpected.toISOString().slice(0, 10) === day) {
        last.end = day;
        last.days += 1;
        continue;
      }
    }
    ranges.push({ start: day, end: day, days: 1 });
  }
  return ranges.sort((a, b) => b.days - a.days);
}

const gapRecommendation = (t: Translate, missingDays: number): string => {
  if (missingDays === 0) return t("quality.recommendationComplete");
  if (missingDays <= 3) return t("quality.recommendationMinor");
  return t("quality.recommendationSerious");
};

export default function DataQualityTab({ apiBase }: Props) {
  const { t, locale, formatDate, formatNumber } = useI18n();

  // The two expensive scans, read from their scheduled run rather than computed
  // on arrival. `windowDays` is the window the *run* used, not a live query
  // parameter: changing it here would ask for a different report, not re-filter
  // this one, so the selector is driven from the run's own params.
  const gapReport = useReport<GapReport>(apiBase, "gaps");
  const conflictReport = useReport<ConflictReport>(apiBase, "conflicts");
  const gaps: Gap[] = gapReport.result?.gaps ?? [];
  const cadenceGaps: CadenceGap[] = gapReport.result?.cadence_gaps ?? [];
  const conflictItems: Conflict[] = conflictReport.result?.conflicts ?? [];
  const conflicts = conflictItems.length;
  const windowDays = Number(gapReport.params?.window_days ?? 30);

  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [backfill, setBackfill] = useState<{
    sourceId: string;
    sourceType: string;
    sourceName: string;
  } | null>(null);

  /**
   * The connector list, which is all this page still fetches live.
   *
   * The quarantine, unsupported-field and newly-supported lists moved to each
   * connector's own page — they are per-connector decisions, and every row
   * already carried the `source_id` that says so. The two expensive scans that
   * remain here, gaps and cross-source conflicts, come from a scheduled run
   * (`useReport` above) because they walk the workspace's whole history and
   * cannot answer differently until an import has changed it.
   *
   * The connectors are still needed: the gap list offers a backfill per
   * connector, and the conflict list names which one reported each value.
   */
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const connectorRes = await apiFetch(`${apiBase}/api/v1/data/sources`);
      if (connectorRes.ok) setConnectors((await connectorRes.json()).connectors ?? []);
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) await load();
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  // Not polled. Nothing on this page changes on its own: the two expensive
  // derivations are recomputed by a report run rather than by looking at the
  // page. A timer here re-ran a full-history gap scan and a 5,000-row conflict
  // scan every fifteen seconds to redraw identical content.
  usePolling(() => void load(), null);

  const missingTotal = gaps.reduce((sum, gap) => sum + gap.missing_dates.length, 0);
  const cards = [
    {
      title: t("quality.gapsTitle"),
      value: missingTotal,
      icon: CalendarX2,
      detail: t("quality.gapsDetail", { metrics: gaps.length, days: windowDays }),
      help: gapRecommendation(t, missingTotal),
    },
    {
      title: t("quality.conflictsTitle"),
      // "—", not 0, until the scan has actually run. A zero here read as
      // "checked, nothing found" when the truth was "never checked", and
      // nothing else on the card distinguished the two. A wrong number is worse
      // than a missing one, because nothing marks it as wrong.
      value: conflictReport.status === "ready" ? conflicts : "—",
      icon: AlertTriangle,
      detail: t("quality.conflictsDetail"),
      help:
        conflictReport.status !== "ready"
          ? t("report.neverComputed")
          : conflicts === 0
            ? t("quality.conflictsNone")
            : t("quality.conflictsHelp"),
    },
  ];

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-ok-ink">
            {t("quality.eyebrow")}
          </p>
          <h1 className="text-3xl font-extrabold text-ink">{t("quality.title")}</h1>
          <p className="mt-2 text-sm text-ink-muted">{t("quality.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs font-semibold text-ink-muted">
            {t("quality.window")}
            <select
              value={windowDays}
              // Another window is another report, not a filter over this one, so
              // this queues a run rather than re-rendering what is already here.
              onChange={(e) =>
                void gapReport.refresh({
                  window_days: Number(e.target.value),
                  offset_minutes: -new Date().getTimezoneOffset(),
                })
              }
              disabled={gapReport.running}
              className="ml-2 rounded-xl border border-line bg-surface px-2.5 py-1.5 text-xs text-ink-secondary outline-none focus-ring disabled:opacity-50"
            >
              {[7, 30, 90, 180, 365].map((days) => (
                <option key={days} value={days}>
                  {t("quality.windowDays", { count: days })}
                </option>
              ))}
            </select>
          </label>
          {loading && <RefreshCw className="h-5 w-5 animate-spin text-ok-ink" />}
        </div>
      </div>

      <ReportStatus
        computedAt={gapReport.computed_at}
        stale={gapReport.stale || conflictReport.stale}
        running={gapReport.running || conflictReport.running}
        neverComputed={gapReport.status === "never_computed" && !gapReport.loading}
        onRefresh={() => {
          void gapReport.refresh({
            window_days: windowDays,
            offset_minutes: -new Date().getTimezoneOffset(),
          });
          void conflictReport.refresh();
        }}
      />

      <div className="grid gap-4 md:grid-cols-2">
        {cards.map(({ title, value, icon: Icon, detail, help }) => (
          <article
            key={title}
            className="rounded-3xl border border-line bg-surface p-5 shadow-sm"
          >
            <Icon className="mb-5 h-6 w-6 text-ok-ink" />
            <p className="text-sm font-semibold text-ink-muted">{title}</p>
            <p className="text-4xl font-black text-ink">{value}</p>
            <p className="mt-2 text-xs text-ink-muted">{detail}</p>
            <p className="mt-3 rounded-2xl bg-ok-soft p-3 text-xs font-semibold text-ok-ink">
              {help}
            </p>
          </article>
        ))}
      </div>

      <article className="rounded-3xl border border-warn-line bg-warn-soft p-5">
        <div className="flex gap-3">
          <Lightbulb className="h-5 w-5 shrink-0 text-warn-ink" />
          <div>
            <h2 className="font-bold text-ink">{t("quality.explainTitle")}</h2>
            <p className="mt-1 text-sm text-ink-muted">{t("quality.explainBody")}</p>
            <a
              href="/docs/features/data-quality/"
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-warn-ink underline"
            >
              <BookOpen className="h-3.5 w-3.5" /> {t("quality.explainDocs")}
            </a>
          </div>
        </div>
      </article>

      {/*
        Fields this platform is being given and does not store. The question a user
        cannot otherwise ask — "is my device sending something that never arrives?"
        — and the reason four Apple Health quantities went missing for months
        without anyone being able to notice.
      */}
      {/*
        Continuous metrics report interrupted spans, not missing days. They are
        shown separately because they answer a different question — "the watch
        stopped for a week" rather than "no value on the 3rd".
      */}
      {cadenceGaps.length > 0 && (
        <article className="rounded-3xl border border-line bg-surface p-6">
          <h2 className="mb-1 font-bold text-ink">{t("quality.interruptionsTitle")}</h2>
          <p className="mb-4 text-xs leading-relaxed text-ink-muted">
            {t("quality.interruptionsHint")}
          </p>
          <ul className="space-y-2">
            {cadenceGaps.map((gap) => (
              <li key={gap.metric_type} className="rounded-2xl bg-page px-3.5 py-2.5">
                <div className="text-xs font-bold text-ink">{gap.metric_type}</div>
                <ul className="mt-1 space-y-0.5">
                  {gap.missing_ranges.slice(0, 5).map((range) => (
                    <li key={range.start} className="text-[11px] text-ink-muted">
                      {formatDate(range.start)} – {formatDate(range.end)}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </article>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <article className="rounded-3xl border border-line bg-surface p-6">
          <h2 className="mb-1 font-bold text-ink">{t("quality.largestGaps")}</h2>
          <p className="mb-4 text-xs text-ink-muted">{t("quality.largestGapsHint")}</p>

          {gaps.length === 0 ? (
            <p className="text-sm text-ink-muted">{t("quality.noGaps", { days: windowDays })}</p>
          ) : (
            gaps.slice(0, 6).map((gap) => {
              const ranges = toRanges(gap.missing_dates);
              return (
                <div key={gap.metric_type} className="border-b border-line py-3">
                  <div className="flex justify-between text-sm">
                    <span className="font-medium text-ink-secondary">{gap.metric_type}</span>
                    <span className="font-bold text-warn">
                      {t(plural(gap.missing_dates.length, "common.days_one", "common.days_other"), {
                        count: gap.missing_dates.length,
                      })}
                    </span>
                  </div>
                  <ul className="mt-1.5 space-y-1">
                    {ranges.slice(0, 3).map((r) => (
                      <li
                        key={`${r.start}-${r.end}`}
                        className="flex items-center justify-between rounded-lg bg-page px-2.5 py-1.5 text-[11px]"
                      >
                        <span className="font-mono text-ink-muted">
                          {r.start === r.end
                            ? formatDate(`${r.start}T00:00:00Z`)
                            : `${formatDate(`${r.start}T00:00:00Z`)} – ${formatDate(
                                `${r.end}T00:00:00Z`,
                              )}`}
                        </span>
                        <span className="text-ink-muted">
                          {t(plural(r.days, "common.days_one", "common.days_other"), {
                            count: r.days,
                          })}
                        </span>
                      </li>
                    ))}
                    {ranges.length > 3 && (
                      <li className="text-[11px] text-ink-muted">
                        {t("quality.moreRanges", { count: ranges.length - 3 })}
                      </li>
                    )}
                  </ul>
                  <p className="mt-1.5 text-xs text-ink-muted">
                    {gapRecommendation(t, gap.missing_dates.length)}
                  </p>
                </div>
              );
            })
          )}

          {gaps.length > 0 && connectors.length > 0 && (
            <div className="mt-4 border-t border-line pt-4">
              <p className="mb-2 text-xs font-semibold text-ink-muted">
                {t("quality.backfillTitle")}
              </p>
              <div className="flex flex-wrap gap-2">
                {connectors.map((c) => (
                  <button
                    key={c.source_id}
                    onClick={() =>
                      setBackfill({
                        sourceId: c.source_id,
                        sourceType: c.source_type,
                        sourceName: c.display_name || c.source_type,
                      })
                    }
                    className="rounded-xl border border-ok-line bg-ok-soft px-3 py-1.5 text-[11px] font-semibold text-ok-ink hover:bg-ok-soft"
                  >
                    {t("quality.backfillSource", { source: c.source_type })}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-ink-muted">{t("quality.backfillHint")}</p>
            </div>
          )}
        </article>

        {/*
          The disagreements themselves.

          The card that stood here rendered none of them: it branched on
          `conflicts === 0` — a count that falls back to zero when the scan has
          never run — and told the reader to "check the units and pick a primary
          source" for items nothing on the page could name. The scan has always
          sent metric, day, and every candidate's connector and value; only the
          client threw them away.

          Which one is right is deliberately not decided here. Both readings are
          kept, and the choice of a primary source per metric is a separate,
          explicit act.
        */}
        <article className="rounded-3xl border border-line bg-surface p-6">
          <h2 className="mb-1 font-bold text-ink">{t("quality.conflictsListTitle")}</h2>
          <p className="mb-4 text-xs text-ink-muted">{t("quality.conflictsListHint")}</p>

          {conflictReport.status !== "ready" ? (
            <p className="text-sm text-ink-muted">{t("report.neverComputed")}</p>
          ) : conflictItems.length === 0 ? (
            <p className="text-sm text-ink-muted">{t("quality.conflictsNone")}</p>
          ) : (
            <>
              {conflictItems.slice(0, CONFLICTS_SHOWN).map((conflict) => {
                const described = describeMetric(conflict.metric_type, locale);
                return (
                  <div
                    key={`${conflict.metric_type}:${conflict.date}`}
                    className="border-b border-line py-3"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                      <span className="font-medium text-ink-secondary">{described.label}</span>
                      <span className="text-xs text-ink-muted">
                        {formatDate(`${conflict.date}T00:00:00Z`)}
                      </span>
                    </div>
                    <ul className="mt-1.5 space-y-1">
                      {conflict.candidates.map((candidate) => (
                        <li
                          key={candidate.id}
                          className="flex items-baseline justify-between gap-3 rounded-lg bg-page px-2.5 py-1.5 text-[11px]"
                        >
                          <span className="min-w-0 truncate text-ink-muted">
                            {connectorLabel(connectors, candidate.source_id)}
                          </span>
                          <span className="shrink-0 font-mono tabular-nums text-ink">
                            {candidate.value === null
                              ? "—"
                              : formatNumber(candidate.value, {
                                  maximumFractionDigits: described.precision,
                                })}{" "}
                            <span className="font-normal text-ink-muted">{described.unit}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
              {conflictItems.length > CONFLICTS_SHOWN && (
                <p className="mt-3 text-[11px] text-ink-muted">
                  {t("quality.conflictsMore", { count: conflictItems.length - CONFLICTS_SHOWN })}
                </p>
              )}
            </>
          )}

          <p className="mt-4 text-xs text-ink-muted">{t("quality.conflictsHelp")}</p>
        </article>
      </div>

      {backfill && (
        <ImportDialog
          key={backfill.sourceId}
          apiBase={apiBase}
          sourceType={backfill.sourceId}
          sourceName={backfill.sourceName}
          providerType={backfill.sourceType}
          fileImport={backfill.sourceType === "apple_health" || backfill.sourceType === "whoop"}
          isOpen={true}
          onClose={() => setBackfill(null)}
          onQueued={load}
        />
      )}
    </section>
  );
}
