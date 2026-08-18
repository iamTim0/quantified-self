"use client";

import React, { useMemo, useState } from "react";
import { ArrowRight, Database } from "lucide-react";
import { useI18n, type MessageKey } from "../lib/i18n/provider";
import { describeMetric } from "../lib/metrics/catalog";

/**
 * One row per metric type the workspace holds, and the way into its raw points.
 *
 * The numbers come from `/api/v1/data/metrics/summary`, which groups in SQL over the
 * tenant's whole history. Deriving them from the points the explorer has loaded would
 * have been cheaper and wrong twice over: the count would describe the sample rather
 * than the data, and a metric absent from the newest thousand points would not appear
 * at all — which is precisely the metric someone opens this view to find.
 */
export interface MetricSummaryEntry {
  count: number;
  average: number | null;
  min: number | null;
  max: number | null;
  sum: number | null;
  latest_timestamp: string | null;
  /** The registry entry, or `null` for a name written before a catalog change. */
  definition: {
    unit: string;
    aggregation: "average" | "sum" | "last" | "max";
    category: string;
    precision: number;
  } | null;
}

/**
 * What Core stores about how finely a metric is kept on the way in.
 *
 * `effective_from` is the discriminator that matters to a reader: `null` means no
 * workspace override exists and `resolution` is simply the registry's default.
 */
export interface IngestPolicy {
  metric_type: string;
  resolution: string;
  default_resolution: string;
  effective_from: string | null;
}

/**
 * The resolutions this table offers, finest first.
 *
 * `second` is in the list because the registry uses it, and it is not merely a
 * smaller `minute`: `metrics.py` describes it as "keep what the device sent",
 * for series a watch samples irregularly. Leaving it out would not have removed
 * the tier — it would have left a metric stored at `second` preselecting the
 * first option instead, so the control would have reported `raw` while the
 * database said otherwise. That is the exact failure this whole change is about.
 */
const RESOLUTIONS = ["raw", "second", "minute", "hour", "day"] as const;

export type StorableResolution = (typeof RESOLUTIONS)[number];

const RESOLUTION_LABEL: Record<StorableResolution, MessageKey> = {
  raw: "explorer.resolutionRaw",
  second: "explorer.resolutionSecond",
  minute: "explorer.resolutionMinute",
  hour: "explorer.resolutionHour",
  day: "explorer.resolutionDay",
};

function isStorable(value: string): value is StorableResolution {
  return (RESOLUTIONS as readonly string[]).includes(value);
}

interface ExplorerMetricOverviewProps {
  summary: Record<string, MetricSummaryEntry>;
  failed: boolean;
  /** Filter over the metric name, shared with the other views' search box. */
  search: string;
  onShowRaw: (metricType: string) => void;
  /** Effective ingest policy per metric, as stored. */
  policies: Record<string, IngestPolicy>;
  /** Writes one metric's resolution. Resolves false when the write was refused. */
  onApplyResolution: (metricType: string, resolution: StorableResolution) => Promise<boolean>;
}

/** Which of the four aggregates this metric is actually described by. */
const AGGREGATION_LABEL: Record<string, MessageKey> = {
  average: "explorer.aggAverage",
  sum: "explorer.aggSum",
  max: "explorer.aggMax",
  last: "explorer.aggLast",
};

export default function ExplorerMetricOverview({
  summary,
  failed,
  search,
  onShowRaw,
  policies,
  onApplyResolution,
}: ExplorerMetricOverviewProps) {
  const { t, locale, formatDateTime, formatNumber } = useI18n();
  /**
   * The resolution the reader has picked but not yet applied, per metric.
   *
   * Two steps on purpose. In its previous home — the filter bar, between the
   * source and period selects — this control looked like a filter and wrote on
   * `change`, immediately and across every selected metric. It decides what
   * future imports *keep*, so it gets a deliberate second action and a sentence
   * saying what it does.
   */
  const [pending, setPending] = useState<Record<string, StorableResolution>>({});
  const [saving, setSaving] = useState<string | null>(null);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return Object.entries(summary)
      .filter(([key]) => {
        if (!needle) return true;
        const { label } = describeMetric(key, locale);
        return key.toLowerCase().includes(needle) || label.toLowerCase().includes(needle);
      })
      .sort((a, b) => b[1].count - a[1].count);
  }, [summary, search, locale]);

  return (
    <div className="glass-card space-y-4 rounded-3xl border border-line bg-surface p-6">
      <div className="flex items-start gap-2">
        <Database className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
        <div className="space-y-1">
          <p className="text-xs leading-relaxed text-ink-muted">{t("explorer.overviewHint")}</p>
          <p className="text-xs leading-relaxed text-ink-muted">{t("explorer.storageHint")}</p>
        </div>
      </div>

      {failed ? (
        <p className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-xs text-danger-ink-on-soft">
          {t("explorer.overviewFailed")}
        </p>
      ) : rows.length === 0 ? (
        <p className="py-4 text-xs text-ink-muted">
          {Object.keys(summary).length === 0
            ? t("explorer.overviewEmpty")
            : t("explorer.metricsNoMatch")}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-line text-meta font-bold uppercase tracking-wider text-ink-muted">
                <th className="px-3 pb-3">{t("explorer.colMetric")}</th>
                <th className="px-3 pb-3">{t("explorer.colUnit")}</th>
                <th className="px-3 pb-3 text-right">{t("explorer.colPoints")}</th>
                <th className="px-3 pb-3 text-right">{t("explorer.colTypical")}</th>
                <th className="px-3 pb-3 text-right">{t("explorer.colRange")}</th>
                <th className="px-3 pb-3">{t("explorer.colLatest")}</th>
                <th className="px-3 pb-3">{t("explorer.colStorage")}</th>
                <th className="px-3 pb-3 text-right">{t("explorer.colDetails")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map(([key, entry]) => {
                const { label, unit, precision } = describeMetric(key, locale);
                const aggregation = entry.definition?.aggregation ?? "average";
                /*
                  Which number describes a metric is a property of the metric, not a
                  choice this table gets to make: averaging a day's step counts
                  answers a question nobody asked, and totalling a body weight is
                  meaningless. So the column shows the one the registry names and
                  says which one it is.
                */
                const typical =
                  aggregation === "sum"
                    ? entry.sum
                    : aggregation === "max"
                      ? entry.max
                      : aggregation === "last"
                        ? null
                        : entry.average;
                const format = (value: number | null) =>
                  value === null ? "—" : formatNumber(value, { maximumFractionDigits: precision });

                return (
                  <tr key={key} className="transition-colors hover:bg-page">
                    <td className="px-3 py-3">
                      <span className="block font-bold text-ink">{label}</span>
                      <span className="block font-mono text-meta text-ink-muted">{key}</span>
                      {!entry.definition && (
                        <span className="mt-0.5 inline-block rounded-full border border-warn-line bg-warn-soft px-1.5 text-nav font-bold uppercase tracking-wider text-warn-ink">
                          {t("explorer.unregistered")}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 font-mono text-ink-muted">{unit || "—"}</td>
                    <td className="px-3 py-3 text-right font-mono font-bold text-ink">
                      {formatNumber(entry.count)}
                    </td>
                    <td className="px-3 py-3 text-right">
                      <span className="block font-mono font-bold text-ink">
                        {format(typical)}
                      </span>
                      <span className="block text-meta text-ink-muted">
                        {t(AGGREGATION_LABEL[aggregation] ?? "explorer.aggAverage")}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right font-mono text-meta text-ink-muted">
                      {format(entry.min)} / {format(entry.max)}
                    </td>
                    <td className="px-3 py-3 text-meta text-ink-muted">
                      {entry.latest_timestamp ? formatDateTime(entry.latest_timestamp) : "—"}
                    </td>
                    <td className="px-3 py-3">
                      {(() => {
                        const policy = policies[key];
                        // A metric with no registry entry has no policy to set:
                        // Core rejects a non-canonical name on this endpoint, so
                        // offering the control would only produce a 422.
                        if (!policy || !entry.definition) {
                          return <span className="text-meta text-ink-muted">—</span>;
                        }
                        // A resolution this build does not know about is shown as
                        // itself rather than offered in a select, where it would
                        // preselect the first option and misreport what is stored.
                        if (!isStorable(policy.resolution)) {
                          return (
                            <span className="font-mono text-meta text-ink-muted">
                              {policy.resolution}
                            </span>
                          );
                        }
                        const stored = policy.resolution;
                        const choice = pending[key] ?? stored;
                        const dirty = choice !== stored;
                        return (
                          <div className="flex flex-col items-start gap-1">
                            <select
                              value={choice}
                              aria-label={t("explorer.colStorage")}
                              disabled={saving === key}
                              onChange={(event) =>
                                setPending((previous) => ({
                                  ...previous,
                                  [key]: event.target.value as StorableResolution,
                                }))
                              }
                              className="min-h-9 rounded-xl border border-line bg-surface px-2 py-1 text-meta font-semibold text-ink outline-none focus-ring disabled:opacity-50"
                            >
                              {RESOLUTIONS.map((resolution) => (
                                <option key={resolution} value={resolution}>
                                  {t(RESOLUTION_LABEL[resolution])}
                                </option>
                              ))}
                            </select>
                            {dirty ? (
                              <button
                                type="button"
                                disabled={saving === key}
                                onClick={async () => {
                                  setSaving(key);
                                  const ok = await onApplyResolution(key, choice);
                                  setSaving(null);
                                  if (ok) {
                                    setPending((previous) => {
                                      const next = { ...previous };
                                      delete next[key];
                                      return next;
                                    });
                                  }
                                }}
                                className="min-h-9 rounded-xl border border-warn-line bg-warn-soft px-2.5 text-meta font-bold text-warn-ink hover:bg-warn-soft disabled:opacity-50"
                              >
                                {t("explorer.storageApply")}
                              </button>
                            ) : (
                              <span className="text-meta text-ink-muted">
                                {policy.effective_from === null
                                  ? t("explorer.storageIsDefault")
                                  : t("explorer.storageIsOverride")}
                              </span>
                            )}
                          </div>
                        );
                      })()}
                    </td>
                    <td className="px-3 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => onShowRaw(key)}
                        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-xl border border-line bg-surface px-2.5 py-1.5 text-meta font-bold text-ink-secondary transition-colors hover:border-brand hover:text-brand"
                      >
                        {t("explorer.showRaw")}
                        <ArrowRight className="h-3 w-3" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
