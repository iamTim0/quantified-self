"use client";

import React from "react";
import { ChevronRight } from "lucide-react";
import { useI18n } from "../lib/i18n/provider";
import { plural } from "../lib/i18n/translate";
import { describeMetric } from "../lib/metrics/catalog";
import type { DataPointItem } from "./ExplorerTab";

/**
 * The stored points themselves, newest first — the log behind every chart.
 *
 * Rows are capped for the DOM's sake, not silently: the count above states how many
 * matched and the note below states how many are drawn, because a table that shows
 * a hundred rows out of nine hundred and says nothing reads as the whole answer.
 */
const MAX_ROWS = 200;

interface ExplorerRawTableProps {
  points: DataPointItem[];
  onInspect: (point: DataPointItem) => void;
}

export default function ExplorerRawTable({ points, onInspect }: ExplorerRawTableProps) {
  const { t, locale, formatDateTime, formatNumber } = useI18n();
  const rows = points.slice(0, MAX_ROWS);

  return (
    <div className="glass-card space-y-4 rounded-3xl border border-slate-200/80 bg-white p-6">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-slate-900">
          {t("explorer.tabRaw")}{" "}
          <span className="font-normal text-slate-400">
            {t(plural(points.length, "explorer.rawCount_one", "explorer.rawCount_other"), {
              count: formatNumber(points.length),
            })}
          </span>
        </h3>
        <span className="font-mono text-[11px] text-slate-400">{t("explorer.liveQuery")}</span>
      </div>

      {rows.length === 0 ? (
        <p className="py-4 text-xs text-slate-400">{t("explorer.empty")}</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                  <th className="px-3 pb-3">{t("explorer.colTimestamp")}</th>
                  <th className="px-3 pb-3">{t("explorer.colSource")}</th>
                  <th className="px-3 pb-3">{t("explorer.colMetric")}</th>
                  <th className="px-3 pb-3">{t("explorer.colValue")}</th>
                  <th className="px-3 pb-3">{t("explorer.colMetadata")}</th>
                  <th className="px-3 pb-3 text-right">{t("explorer.colDetails")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((point) => {
                  const { label, unit, precision } = describeMetric(point.metric_type, locale);
                  const itemName = point.metadata?.food_name || point.metadata?.name;
                  return (
                    <tr key={point.id} className="font-mono transition-colors hover:bg-slate-50">
                      {/*
                        Formatted for the reader, exact in the tooltip. The stored
                        instant is what someone reconciling against the database
                        needs, and it used to be the only thing on offer — an ISO
                        string with its `T` and `Z` stripped out, which is neither
                        the reader's format nor the database's value.
                      */}
                      <td
                        className="px-3 py-2.5 text-[11px] text-slate-500"
                        title={point.timestamp}
                      >
                        {point.timestamp ? formatDateTime(point.timestamp) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-[10px] font-bold uppercase text-slate-900">
                        {/*
                          `|| "yazio"` before this, so every point whose metadata
                          carried no source was labelled as the one connector that
                          happened to be built first.
                        */}
                        <span className="rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-slate-700">
                          {point.source_type || point.metadata?.source_type || t("common.unknown")}
                        </span>
                      </td>
                      <td className="px-3 py-2.5" title={point.metric_type}>
                        <span className="font-sans font-bold text-[#0d5c3a]">{label}</span>
                      </td>
                      {/*
                        Rounded to the precision the registry declares for this
                        metric, not to a blanket default: `Intl.NumberFormat` stops
                        at three fraction digits on its own, which is a different
                        town for a coordinate the registry carries to six. The
                        stored value is in the tooltip either way.
                      */}
                      <td
                        className="px-3 py-2.5 font-bold text-slate-900"
                        title={String(point.value)}
                      >
                        {formatNumber(point.value, { maximumFractionDigits: precision })}
                        {/* The unit is a property of the metric, so a raw value is
                            ambiguous without it -- which is how kJ and kcal used to
                            sit in one column looking comparable. */}
                        {unit && (
                          <span className="ml-1 text-[10px] font-normal text-slate-500">
                            {unit}
                          </span>
                        )}
                      </td>
                      <td className="max-w-xs truncate px-3 py-2.5 text-[11px] text-slate-500">
                        {itemName ? (
                          <span className="mr-1.5 font-sans font-bold text-emerald-700">
                            {itemName}
                          </span>
                        ) : null}
                        <span className="text-slate-400">
                          {JSON.stringify(point.metadata || {})}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <button
                          type="button"
                          onClick={() => onInspect(point)}
                          title={t("explorer.inspect")}
                          aria-label={t("explorer.inspect")}
                          className="p-1 text-slate-400 transition-colors hover:text-[#0d5c3a]"
                        >
                          <ChevronRight className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {points.length > rows.length && (
            <p className="text-[11px] text-slate-400">
              {t("explorer.rawTruncated", {
                shown: formatNumber(rows.length),
                total: formatNumber(points.length),
              })}
            </p>
          )}
        </>
      )}
    </div>
  );
}
