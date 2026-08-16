"use client";

import { RefreshCw } from "lucide-react";
import { useI18n, type MessageKey } from "../lib/i18n/provider";

const REPORT_ERROR_KEYS: Record<string, MessageKey> = {
  report_failed: "report.error.report_failed",
  insights_failed: "report.error.insights_failed",
  report_load_failed: "report.error.report_load_failed",
  report_refresh_failed: "report.error.report_refresh_failed",
};

/**
 * When a precomputed report was last true, and a way to ask for a newer one.
 *
 * Shown above every derived view. A reader looking at a number that was computed
 * some hours ago needs two things: the time it was computed, and whether the
 * data has moved on since. The second is not a guess — the server compares the
 * run against the workspace's newest finished import and says so.
 */
export default function ReportStatus({
  computedAt,
  stale,
  running,
  neverComputed,
  error,
  onRefresh,
}: {
  computedAt: string | null;
  stale: boolean;
  running: boolean;
  neverComputed: boolean;
  error?: {
    code: string;
    params: Record<string, string | number | boolean>;
    message?: string | null;
  } | null;
  onRefresh: () => void;
}) {
  const { t, formatDateTime } = useI18n();
  const errorText = error
    ? (() => {
        const code = error.code.startsWith("insights_failed_") ? "insights_failed" : error.code;
        const key = REPORT_ERROR_KEYS[code];
        if (!key) return error.message || t("report.failed");
        const vars = Object.fromEntries(
          Object.entries(error.params).filter(
            (entry): entry is [string, string | number] =>
              typeof entry[1] === "string" || typeof entry[1] === "number",
          ),
        );
        return t(key, vars);
      })()
    : null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
      {running ? (
        <span className="inline-flex items-center gap-1.5">
          <RefreshCw className="h-3 w-3 animate-spin" aria-hidden="true" />
          {t("report.running")}
        </span>
      ) : neverComputed ? (
        <span>{t("report.neverComputed")}</span>
      ) : (
        <span>
          {t("report.computedAt", {
            timestamp: computedAt ? formatDateTime(computedAt) : "—",
          })}
        </span>
      )}

      {error && !running ? (
        <span className="rounded-full bg-red-100 px-2 py-0.5 font-medium text-red-800 dark:bg-red-500/15 dark:text-red-300">
          {errorText}
        </span>
      ) : null}

      {stale && !running && !neverComputed ? (
        <span className="rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">
          {t("report.stale")}
        </span>
      ) : null}

      <button
        type="button"
        onClick={onRefresh}
        disabled={running}
        className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-2 py-1 font-medium text-slate-700 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
      >
        <RefreshCw className="h-3 w-3" aria-hidden="true" />
        {t("report.recompute")}
      </button>
    </div>
  );
}
