"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, BookOpen, CalendarX2, Lightbulb, RefreshCw } from "lucide-react";
import ImportDialog from "./ImportDialog";
import ReportStatus from "./ReportStatus";
import { plural, useI18n, type Translate } from "../lib/i18n/provider";
import { apiFetch } from "../lib/api";
import { usePolling } from "../lib/polling";
import { useReport } from "../lib/reports";
import { CANONICAL_KEYS, describeMetric } from "../lib/metrics/catalog";

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
 * One provider field that arrives and is not stored.
 *
 * Deliberately shape-only: a path, the kind of value that sat there, and how often
 * it was seen. There is no value field, and there is not meant to be one — keeping
 * payloads would mean a second copy of the most sensitive data in the system.
 */
type UnsupportedField = {
  source_id: string;
  source_type: string;
  connector_name: string;
  field_path: string;
  value_kind: string;
  occurrences: number;
  last_seen_at: string | null;
};

/**
 * A field that used to arrive unstored and is now being stored.
 *
 * The other half of `UnsupportedField`. Vanishing from that list is not an answer:
 * it is indistinguishable from a field that simply stopped arriving.
 */
type NewlySupportedField = {
  source_id: string;
  source_type: string;
  connector_name: string;
  field_path: string;
  metric_type: string | null;
  occurrences: number;
  supported_since: string;
  unstored_from: string | null;
  unstored_until: string;
  /**
   * False for a connector nothing can re-fetch — one fed by a device, or by an
   * export archive that only the user has.
   */
  history_recoverable: boolean;
  /**
   * When the platform re-imported the span this field missed. Null on a
   * recoverable field means the sweep has not reached it yet, not that it is
   * stuck: it runs on its own timer and stamps this only once a run is queued.
   */
  history_backfilled_at: string | null;
};

type QuarantinedMetric = {
  source_id: string;
  source_type: string;
  connector_name: string;
  raw_metric_type: string;
  points: number;
  seen: number;
  units: string | null;
  first_seen_at: string;
  last_seen_at: string;
  action: "map" | "adopt" | "discard" | "keep" | null;
};

type QuarantineWarningCode =
  | "quarantine_has_pending"
  | "quarantine_half_full"
  | "quarantine_near_full"
  | "quarantine_full"
  | "quarantine_values_refused";

type QuarantineCapacity = {
  source_id: string;
  source_type: string;
  connector_name: string;
  active_rows: number;
  max_rows: number;
  active_names: number;
  max_names: number;
  usage_percent: number;
  limiting_dimension: "rows" | "names";
  refused_occurrences: number;
  warning_code: QuarantineWarningCode;
};

type MappingDraft = {
  action: "map" | "adopt" | "discard" | "keep";
  target_metric_type: string;
  source_unit: string;
  target_unit: string;
  aggregation: "average" | "sum" | "last" | "max";
  cadence: "daily" | "continuous" | "event";
  keep_indefinitely: boolean;
};

/** Contiguous runs of missing days, so "12 days" becomes a usable backfill range. */
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
  // Fields a connector is being given and this platform does not store. Shapes
  // only — the response carries a path and a value *kind*, never a value.
  const [unsupported, setUnsupported] = useState<UnsupportedField[]>([]);
  const [newlySupported, setNewlySupported] = useState<NewlySupportedField[]>([]);
  const [quarantine, setQuarantine] = useState<QuarantinedMetric[]>([]);
  const [quarantineCapacity, setQuarantineCapacity] = useState<QuarantineCapacity[]>([]);
  const [mappingDrafts, setMappingDrafts] = useState<Record<string, MappingDraft>>({});
  const [savingMapping, setSavingMapping] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [backfill, setBackfill] = useState<{
    sourceId: string;
    sourceType: string;
    sourceName: string;
  } | null>(null);

  /**
   * The three lists that are *state*, not derivation.
   *
   * Quarantine, mapping rules and unsupported fields are small indexed reads and
   * have to be right the instant a user saves a rule, so they stay live. The two
   * expensive scans — gaps and cross-source conflicts — come from a scheduled
   * run instead (`useReport` above), because they walk the workspace's history
   * and cannot answer differently until an import has changed it.
   */
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [connectorRes, unsupportedRes, newlyRes, quarantineRes] = await Promise.all([
        apiFetch(`${apiBase}/api/v1/data/sources`),
        apiFetch(`${apiBase}/api/v1/data/quality/unsupported-fields`),
        apiFetch(`${apiBase}/api/v1/data/quality/newly-supported-fields`),
        apiFetch(`${apiBase}/api/v1/data/quality/quarantine`),
      ]);
      if (connectorRes.ok) setConnectors((await connectorRes.json()).connectors ?? []);
      if (unsupportedRes.ok) setUnsupported((await unsupportedRes.json()).fields ?? []);
      if (newlyRes.ok) setNewlySupported((await newlyRes.json()).fields ?? []);
      if (quarantineRes.ok) {
        const data = await quarantineRes.json();
        setQuarantine(data.metrics ?? []);
        setQuarantineCapacity(data.capacity ?? []);
      }
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  const draftFor = (metric: QuarantinedMetric): MappingDraft => {
    const key = `${metric.source_id}:${metric.raw_metric_type}`;
    return (
      mappingDrafts[key] ?? {
        action: metric.action ?? "keep",
        target_metric_type: CANONICAL_KEYS[0] ?? "steps",
        source_unit: metric.units ?? "count",
        target_unit: "",
        aggregation: "average",
        cadence: "event",
        keep_indefinitely: false,
      }
    );
  };

  const updateDraft = (metric: QuarantinedMetric, change: Partial<MappingDraft>) => {
    const key = `${metric.source_id}:${metric.raw_metric_type}`;
    setMappingDrafts((current) => ({
      ...current,
      [key]: { ...draftFor(metric), ...change },
    }));
  };

  const saveMapping = async (metric: QuarantinedMetric) => {
    const key = `${metric.source_id}:${metric.raw_metric_type}`;
    const draft = draftFor(metric);
    setSavingMapping(key);
    try {
      const response = await apiFetch(`${apiBase}/api/v1/data/quality/mapping-rules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_id: metric.source_id,
          raw_metric_type: metric.raw_metric_type,
          action: draft.action,
          target_metric_type:
            draft.action === "map" || draft.action === "adopt"
              ? draft.target_metric_type
              : undefined,
          source_unit:
            draft.action === "map" || draft.action === "adopt" ? draft.source_unit : undefined,
          target_unit: draft.action === "adopt" ? draft.target_unit : undefined,
          aggregation: draft.action === "adopt" ? draft.aggregation : undefined,
          cadence: draft.action === "adopt" ? draft.cadence : undefined,
          keep_indefinitely: draft.action === "keep" ? draft.keep_indefinitely : false,
        }),
      });
      if (response.ok) await load();
    } finally {
      setSavingMapping(null);
    }
  };

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

  // Not polled. Nothing on this page changes on its own: the quarantine and
  // mapping lists are reloaded by the action that changes them, and the two
  // expensive derivations are recomputed by a report run rather than by looking
  // at the page. A timer here re-ran a full-history gap scan and a 5,000-row
  // conflict scan every fifteen seconds to redraw identical content.
  usePolling(() => void load(), null);

  const quarantineWarningKey = (code: QuarantineWarningCode) => {
    switch (code) {
      case "quarantine_half_full":
        return "quality.quarantineCapacityHalf" as const;
      case "quarantine_near_full":
        return "quality.quarantineCapacityNearFull" as const;
      case "quarantine_full":
        return "quality.quarantineCapacityFull" as const;
      case "quarantine_values_refused":
        return "quality.quarantineCapacityRefused" as const;
      default:
        return "quality.quarantineCapacityPending" as const;
    }
  };

  const quarantineWarningClasses = (code: QuarantineWarningCode) => {
    if (code === "quarantine_values_refused" || code === "quarantine_full") {
      return {
        container: "border-rose-300 bg-danger-soft",
        title: "text-rose-950",
        text: "text-rose-900",
        icon: "text-danger-ink-on-soft",
      };
    }
    if (code === "quarantine_near_full") {
      return {
        container: "border-orange-300 bg-orange-50",
        title: "text-orange-950",
        text: "text-orange-900",
        icon: "text-orange-700",
      };
    }
    if (code === "quarantine_half_full") {
      return {
        container: "border-warn-line bg-warn-soft",
        title: "text-warn-ink",
        text: "text-warn-ink",
        icon: "text-warn-ink",
      };
    }
    return {
      container: "border-violet-300 bg-info-soft",
      title: "text-info-ink",
      text: "text-info-ink",
      icon: "text-violet-700",
    };
  };

  const quarantineCapacityLiveMode = quarantineCapacity.some(
    ({ warning_code }) =>
      warning_code === "quarantine_near_full" ||
      warning_code === "quarantine_full" ||
      warning_code === "quarantine_values_refused",
  )
    ? "assertive"
    : "polite";

  /**
   * A ready-to-paste report of what is not being stored.
   *
   * Carries the provider's field names, their types and how often they were seen —
   * and deliberately nothing else. No values, no connector ids, no workspace
   * identifier: this is meant to be pasted into a public issue tracker, so it must
   * be safe to paste there without anyone having to check it first.
   */
  const copyFieldReport = async () => {
    const bySource = new Map<string, UnsupportedField[]>();
    for (const field of unsupported) {
      const list = bySource.get(field.source_type) ?? [];
      list.push(field);
      bySource.set(field.source_type, list);
    }

    const lines = ["## Unsupported provider fields", ""];
    for (const [sourceType, fields] of [...bySource].sort()) {
      lines.push(`### ${sourceType}`, "");
      lines.push("| Field | Type | Seen |", "| --- | --- | ---: |");
      for (const field of fields) {
        lines.push(`| \`${field.field_path}\` | ${field.value_kind} | ${field.occurrences} |`);
      }
      lines.push("");
    }

    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be refused; the table above is still readable.
    }
  };

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

      {quarantineCapacity.length > 0 && (
        <article className="space-y-3" aria-live={quarantineCapacityLiveMode}>
          <div>
            <h2 className="font-bold text-ink">{t("quality.quarantineCapacityTitle")}</h2>
            <p className="mt-1 text-sm text-ink-muted">{t("quality.quarantineCapacityIntro")}</p>
          </div>
          {quarantineCapacity.map((capacity) => {
            const classes = quarantineWarningClasses(capacity.warning_code);
            return (
              <div
                key={capacity.source_id}
                className={`rounded-3xl border p-5 ${classes.container}`}
              >
                <div className="flex gap-3">
                  <AlertTriangle className={`mt-0.5 h-5 w-5 shrink-0 ${classes.icon}`} />
                  <div className="min-w-0">
                    <h3 className={`font-bold ${classes.title}`}>
                      {capacity.connector_name || capacity.source_type}
                    </h3>
                    <p className={`mt-1 text-sm ${classes.text}`}>
                      {t(quarantineWarningKey(capacity.warning_code), {
                        percent: formatNumber(capacity.usage_percent),
                        rows: formatNumber(capacity.active_rows),
                        maxRows: formatNumber(capacity.max_rows),
                        names: formatNumber(capacity.active_names),
                        maxNames: formatNumber(capacity.max_names),
                        refused: formatNumber(capacity.refused_occurrences),
                      })}
                    </p>
                    <p className={`mt-2 text-xs ${classes.text}`}>
                      {t("quality.quarantineCapacityUsage", {
                        rows: formatNumber(capacity.active_rows),
                        maxRows: formatNumber(capacity.max_rows),
                        names: formatNumber(capacity.active_names),
                        maxNames: formatNumber(capacity.max_names),
                      })}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </article>
      )}

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

      {newlySupported.length > 0 && (
        <section className="rounded-3xl border border-ok-line bg-ok-soft p-6 dark:border-emerald-800/70">
          <h2 className="mb-1 font-bold text-ok-ink dark:text-emerald-100">
            {t("quality.newlySupportedTitle", { count: String(newlySupported.length) })}
          </h2>
          <p className="mb-4 text-xs leading-relaxed text-ok-ink">
            {t("quality.newlySupportedHint")}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-ok-ink">
                <tr>
                  <th className="py-1 pr-4 font-semibold">{t("quality.colConnector")}</th>
                  <th className="py-1 pr-4 font-semibold">{t("quality.colField")}</th>
                  <th className="py-1 pr-4 font-semibold">{t("quality.colMetric")}</th>
                  <th className="py-1 pr-4 font-semibold">{t("quality.colSince")}</th>
                  <th className="py-1 font-semibold">{t("quality.colHistory")}</th>
                </tr>
              </thead>
              <tbody className="text-ok-ink dark:text-emerald-100">
                {newlySupported.map((field) => (
                  <tr
                    key={`${field.source_id}:${field.field_path}`}
                    className="border-t border-emerald-200/70 dark:border-emerald-800/70"
                  >
                    <td className="py-1.5 pr-4">{field.connector_name}</td>
                    <td className="py-1.5 pr-4 font-mono">{field.field_path}</td>
                    <td className="py-1.5 pr-4 font-mono">{field.metric_type ?? "—"}</td>
                    <td className="py-1.5 pr-4">{formatDate(field.supported_since)}</td>
                    <td className="py-1.5">
                      {/* Three states, not two. "Recoverable" was a statement about
                          what was possible, which read as an instruction to go and
                          do it — and the platform now does it by itself, so the
                          column has to say whether that has happened yet. Said
                          plainly rather than offered as a button, because for a
                          connector fed by a device or an archive nothing here can
                          ask for the data again. */}
                      {!field.history_recoverable
                        ? t("quality.historyOnDevice")
                        : field.history_backfilled_at
                          ? t("quality.historyRecovered", {
                              date: formatDate(field.history_backfilled_at),
                            })
                          : t("quality.historyQueued")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {unsupported.length > 0 && (
        <details className="group rounded-3xl border border-warn-line bg-warn-soft p-6">
          <summary className="cursor-pointer list-none font-bold text-warn-ink marker:hidden">
            <span className="flex items-center justify-between gap-3">
              <span>{t("quality.unsupportedSummary", { count: unsupported.length })}</span>
              <span className="text-xs font-semibold text-warn-ink transition group-open:rotate-180">
                ↓
              </span>
            </span>
          </summary>
          <div className="mt-4">
            <h2 className="mb-1 font-bold text-warn-ink">
              {t("quality.unsupportedTitle")}
            </h2>
            <p className="mb-2 text-xs leading-relaxed text-warn-ink">
              {t("quality.unsupportedHint")}
            </p>
            <p className="mb-4 text-xs leading-relaxed text-warn-ink">
              {t("quality.unsupportedLifecycle")}
            </p>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-warn-line text-[11px] font-bold uppercase tracking-wider text-warn-ink">
                    <th className="pb-2 pr-3">{t("quality.unsupportedConnector")}</th>
                    <th className="pb-2 pr-3">{t("quality.unsupportedField")}</th>
                    <th className="pb-2 pr-3">{t("quality.unsupportedKind")}</th>
                    <th className="pb-2 pr-3 text-right">{t("quality.unsupportedSeen")}</th>
                    <th className="pb-2 text-right">{t("quality.unsupportedLastSeen")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-warn-line">
                  {unsupported.map((field) => (
                    <tr key={`${field.source_id}:${field.field_path}`}>
                      <td className="py-2 pr-3 font-semibold text-warn-ink">
                        {field.connector_name || field.source_type}
                      </td>
                      <td className="py-2 pr-3 font-mono text-warn-ink">
                        {field.field_path}
                      </td>
                      <td className="py-2 pr-3 text-warn-ink">
                        {field.value_kind}
                      </td>
                      <td className="py-2 pr-3 text-right text-warn-ink">
                        {field.occurrences}
                      </td>
                      <td className="py-2 text-right text-warn-ink">
                        {formatDate(field.last_seen_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <button
              type="button"
              onClick={() => void copyFieldReport()}
              className="mt-4 inline-flex items-center gap-1.5 rounded-2xl border border-warn-line bg-surface px-3.5 py-2 text-xs font-semibold text-warn-ink hover:bg-warn-soft"
            >
              {copied ? t("quality.unsupportedCopied") : t("quality.unsupportedCopy")}
            </button>
          </div>
        </details>
      )}

      {quarantine.length > 0 && (
        <article className="rounded-3xl border border-info-line bg-info-soft p-6">
          <h2 className="mb-1 font-bold text-info-ink">{t("quality.quarantineTitle")}</h2>
          <p className="mb-4 text-xs leading-relaxed text-info-ink">
            {t("quality.quarantineHint")}
          </p>
          <div className="space-y-4">
            {quarantine.map((metric) => {
              const key = `${metric.source_id}:${metric.raw_metric_type}`;
              const draft = draftFor(metric);
              return (
                <div key={key} className="rounded-2xl border border-info-line bg-surface p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-sm font-semibold text-ink">
                        {metric.raw_metric_type}
                      </p>
                      <p className="mt-1 text-xs text-ink-muted">
                        {t("quality.quarantineConnectorDetail", {
                          connector: metric.connector_name || metric.source_type,
                          count: metric.points,
                        })}
                      </p>
                    </div>
                    <select
                      value={draft.action}
                      onChange={(event) =>
                        updateDraft(metric, {
                          action: event.target.value as MappingDraft["action"],
                        })
                      }
                      className="rounded-xl border border-info-line bg-surface px-2.5 py-1.5 text-xs text-ink-secondary"
                      aria-label={t("quality.mappingDecision")}
                    >
                      <option value="map">{t("quality.mappingMap")}</option>
                      <option value="adopt">{t("quality.mappingAdopt")}</option>
                      <option value="discard">{t("quality.mappingDiscard")}</option>
                      <option value="keep">{t("quality.mappingKeep")}</option>
                    </select>
                  </div>

                  {(draft.action === "map" || draft.action === "adopt") && (
                    <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                      {draft.action === "map" ? (
                        <select
                          value={draft.target_metric_type}
                          onChange={(event) =>
                            updateDraft(metric, { target_metric_type: event.target.value })
                          }
                          className="rounded-xl border border-line px-2.5 py-2 text-xs"
                          aria-label={t("quality.mappingTarget")}
                        >
                          {CANONICAL_KEYS.map((keyName) => (
                            <option key={keyName} value={keyName}>
                              {keyName}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          value={draft.target_metric_type}
                          onChange={(event) =>
                            updateDraft(metric, { target_metric_type: event.target.value })
                          }
                          placeholder={t("quality.mappingCustomName")}
                          className="rounded-xl border border-line px-2.5 py-2 text-xs"
                          aria-label={t("quality.mappingTarget")}
                        />
                      )}
                      <input
                        value={draft.source_unit}
                        onChange={(event) =>
                          updateDraft(metric, { source_unit: event.target.value })
                        }
                        placeholder={t("quality.mappingSourceUnit")}
                        className="rounded-xl border border-line px-2.5 py-2 text-xs"
                        aria-label={t("quality.mappingSourceUnit")}
                      />
                      {draft.action === "adopt" && (
                        <>
                          <input
                            value={draft.target_unit}
                            onChange={(event) =>
                              updateDraft(metric, { target_unit: event.target.value })
                            }
                            placeholder={t("quality.mappingTargetUnit")}
                            className="rounded-xl border border-line px-2.5 py-2 text-xs"
                            aria-label={t("quality.mappingTargetUnit")}
                          />
                          <select
                            value={draft.aggregation}
                            onChange={(event) =>
                              updateDraft(metric, {
                                aggregation: event.target.value as MappingDraft["aggregation"],
                              })
                            }
                            className="rounded-xl border border-line px-2.5 py-2 text-xs"
                            aria-label={t("quality.mappingAggregation")}
                          >
                            <option value="average">{t("quality.mappingAverage")}</option>
                            <option value="sum">{t("quality.mappingSum")}</option>
                            <option value="last">{t("quality.mappingLast")}</option>
                            <option value="max">{t("quality.mappingMax")}</option>
                          </select>
                          <select
                            value={draft.cadence}
                            onChange={(event) =>
                              updateDraft(metric, {
                                cadence: event.target.value as MappingDraft["cadence"],
                              })
                            }
                            className="rounded-xl border border-line px-2.5 py-2 text-xs"
                            aria-label={t("quality.mappingCadence")}
                          >
                            <option value="daily">{t("quality.mappingDaily")}</option>
                            <option value="continuous">{t("quality.mappingContinuous")}</option>
                            <option value="event">{t("quality.mappingEvent")}</option>
                          </select>
                        </>
                      )}
                    </div>
                  )}

                  {draft.action === "keep" && (
                    <label className="mt-3 flex items-center gap-2 text-xs text-ink-muted">
                      <input
                        type="checkbox"
                        checked={draft.keep_indefinitely}
                        onChange={(event) =>
                          updateDraft(metric, { keep_indefinitely: event.target.checked })
                        }
                        className="rounded border-line"
                      />
                      {t("quality.mappingKeepIndefinitely")}
                    </label>
                  )}

                  <button
                    type="button"
                    onClick={() => void saveMapping(metric)}
                    disabled={savingMapping === key}
                    className="mt-3 rounded-xl bg-violet-700 px-3.5 py-2 text-xs font-semibold text-white hover:bg-violet-800 disabled:opacity-50"
                  >
                    {savingMapping === key ? t("quality.mappingSaving") : t("quality.mappingApply")}
                  </button>
                </div>
              );
            })}
          </div>
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
