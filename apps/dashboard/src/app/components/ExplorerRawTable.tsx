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
 *
 * The cap is well past the 50 rows at which the interface guidelines ask for
 * virtualization, so each row also carries `content-visibility: auto` — the
 * off-screen ones cost no layout or paint, and unlike a virtualizer they are
 * still in the DOM for find-in-page and for a screen reader.
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
    <div className="glass-card space-y-4 rounded-3xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-ink">
          {t("explorer.tabRaw")}{" "}
          <span className="font-normal text-ink-muted">
            {t(plural(points.length, "explorer.rawCount_one", "explorer.rawCount_other"), {
              count: formatNumber(points.length),
            })}
          </span>
        </h3>
        <span className="font-mono text-meta text-ink-muted">{t("explorer.liveQuery")}</span>
      </div>

      {rows.length === 0 ? (
        <p className="py-4 text-xs text-ink-muted">{t("explorer.empty")}</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-line text-meta font-bold uppercase tracking-wider text-ink-muted">
                  <th className="px-3 pb-3">{t("explorer.colTimestamp")}</th>
                  <th className="px-3 pb-3">{t("explorer.colSource")}</th>
                  <th className="px-3 pb-3">{t("explorer.colMetric")}</th>
                  <th className="px-3 pb-3">{t("explorer.colValue")}</th>
                  <th className="px-3 pb-3">{t("explorer.colMetadata")}</th>
                  <th className="px-3 pb-3 text-right">{t("explorer.colDetails")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((point) => {
                  const { label, unit, precision } = describeMetric(point.metric_type, locale);
                  const itemName = point.metadata?.food_name || point.metadata?.name;
                  return (
                    // `content-visibility-auto` skips layout and paint for rows
                    // scrolled out of view. 200 rows is four times the threshold
                    // at which the interface guidelines ask for virtualization,
                    // and a virtualizer for a table this size would cost more
                    // than it saves — this is one utility and the rows stay in
                    // the DOM, so Ctrl+F and screen readers still find them.
                    // `contain-intrinsic-size` reserves each row's height so the
                    // scrollbar does not jump as they render.
                    <tr
                      key={point.id}
                      className="[contain-intrinsic-size:auto_2.5rem] [content-visibility:auto] font-mono transition-colors hover:bg-page"
                    >
                      {/*
                        Formatted for the reader, exact in the tooltip. The stored
                        instant is what someone reconciling against the database
                        needs, and it used to be the only thing on offer — an ISO
                        string with its `T` and `Z` stripped out, which is neither
                        the reader's format nor the database's value.
                      */}
                      <td
                        className="px-3 py-2.5 text-meta text-ink-muted"
                        title={point.timestamp}
                      >
                        {point.timestamp ? formatDateTime(point.timestamp) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-meta font-bold uppercase text-ink">
                        {/*
                          `|| "yazio"` before this, so every point whose metadata
                          carried no source was labelled as the one connector that
                          happened to be built first.
                        */}
                        <span className="rounded-full border border-line bg-surface-muted px-2 py-0.5 text-ink-secondary">
                          {point.source_type || point.metadata?.source_type || t("common.unknown")}
                        </span>
                      </td>
                      <td className="px-3 py-2.5" title={point.metric_type}>
                        <span className="font-sans font-bold text-brand">{label}</span>
                      </td>
                      {/*
                        Rounded to the precision the registry declares for this
                        metric, not to a blanket default: `Intl.NumberFormat` stops
                        at three fraction digits on its own, which is a different
                        town for a coordinate the registry carries to six. The
                        stored value is in the tooltip either way.
                      */}
                      <td
                        className="px-3 py-2.5 font-bold text-ink"
                        title={String(point.value)}
                      >
                        {formatNumber(point.value, { maximumFractionDigits: precision })}
                        {/* The unit is a property of the metric, so a raw value is
                            ambiguous without it -- which is how kJ and kcal used to
                            sit in one column looking comparable. */}
                        {unit && (
                          <span className="ml-1 text-meta font-normal text-ink-muted">
                            {unit}
                          </span>
                        )}
                      </td>
                      <td className="max-w-xs truncate px-3 py-2.5 text-meta text-ink-muted">
                        {itemName ? (
                          <span className="mr-1.5 font-sans font-bold text-ok-ink">
                            {itemName}
                          </span>
                        ) : null}
                        <span className="text-ink-muted">
                          {JSON.stringify(point.metadata || {})}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <button
                          type="button"
                          onClick={() => onInspect(point)}
                          title={t("explorer.inspect")}
                          aria-label={t("explorer.inspect")}
                          className="p-1 text-ink-muted transition-colors hover:text-brand"
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
            <p className="text-meta text-ink-muted">
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
