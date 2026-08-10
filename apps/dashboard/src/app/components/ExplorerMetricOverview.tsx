"use client";

import React, { useMemo } from "react";
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

interface ExplorerMetricOverviewProps {
  summary: Record<string, MetricSummaryEntry>;
  failed: boolean;
  /** Filter over the metric name, shared with the other views' search box. */
  search: string;
  onShowRaw: (metricType: string) => void;
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
}: ExplorerMetricOverviewProps) {
  const { t, locale, formatDateTime, formatNumber } = useI18n();

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
    <div className="glass-card space-y-4 rounded-3xl border border-slate-200/80 bg-white p-6">
      <div className="flex items-start gap-2">
        <Database className="mt-0.5 h-4 w-4 shrink-0 text-[#0d5c3a]" />
        <p className="text-xs leading-relaxed text-slate-500">{t("explorer.overviewHint")}</p>
      </div>

      {failed ? (
        <p className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-800">
          {t("explorer.overviewFailed")}
        </p>
      ) : rows.length === 0 ? (
        <p className="py-4 text-xs text-slate-400">
          {Object.keys(summary).length === 0
            ? t("explorer.overviewEmpty")
            : t("explorer.metricsNoMatch")}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                <th className="px-3 pb-3">{t("explorer.colMetric")}</th>
                <th className="px-3 pb-3">{t("explorer.colUnit")}</th>
                <th className="px-3 pb-3 text-right">{t("explorer.colPoints")}</th>
                <th className="px-3 pb-3 text-right">{t("explorer.colTypical")}</th>
                <th className="px-3 pb-3 text-right">{t("explorer.colRange")}</th>
                <th className="px-3 pb-3">{t("explorer.colLatest")}</th>
                <th className="px-3 pb-3 text-right">{t("explorer.colDetails")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
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
                  <tr key={key} className="transition-colors hover:bg-slate-50">
                    <td className="px-3 py-3">
                      <span className="block font-bold text-slate-900">{label}</span>
                      <span className="block font-mono text-[10px] text-slate-400">{key}</span>
                      {!entry.definition && (
                        <span className="mt-0.5 inline-block rounded-full border border-amber-200 bg-amber-50 px-1.5 text-[9px] font-bold uppercase tracking-wider text-amber-800">
                          {t("explorer.unregistered")}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 font-mono text-slate-500">{unit || "—"}</td>
                    <td className="px-3 py-3 text-right font-mono font-bold text-slate-900">
                      {formatNumber(entry.count)}
                    </td>
                    <td className="px-3 py-3 text-right">
                      <span className="block font-mono font-bold text-slate-900">
                        {format(typical)}
                      </span>
                      <span className="block text-[10px] text-slate-400">
                        {t(AGGREGATION_LABEL[aggregation] ?? "explorer.aggAverage")}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right font-mono text-[11px] text-slate-500">
                      {format(entry.min)} / {format(entry.max)}
                    </td>
                    <td className="px-3 py-3 text-[11px] text-slate-500">
                      {entry.latest_timestamp ? formatDateTime(entry.latest_timestamp) : "—"}
                    </td>
                    <td className="px-3 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => onShowRaw(key)}
                        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] font-bold text-slate-700 transition-colors hover:border-[#0d5c3a] hover:text-[#0d5c3a]"
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
