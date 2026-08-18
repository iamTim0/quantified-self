"use client";

import { RefreshCw } from "lucide-react";
import { useI18n, type MessageKey } from "../lib/i18n/provider";

const REPORT_ERROR_KEYS: Record<string, MessageKey> = {
  report_failed: "report.error.report_failed",
  insights_failed: "report.error.insights_failed",
  report_load_failed: "report.error.report_load_failed",
  report_refresh_failed: "report.error.report_refresh_failed",
  report_timeout: "report.error.report_timeout",
  report_never_claimed: "report.error.report_never_claimed",
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
  deferred = false,
  running,
  neverComputed,
  error,
  onRefresh,
}: {
  computedAt: string | null;
  stale: boolean;
  /**
   * Stale on purpose: a window of years is recomputed overnight rather than the
   * moment an import lands. Without saying so, "outdated" reads as "forgotten"
   * and invites the reader to press recompute for something already scheduled —
   * which starts the very run the deferral moved out of their way.
   */
  deferred?: boolean;
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
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
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
        <span className="rounded-full bg-danger-soft px-2 py-0.5 font-medium text-danger-ink-on-soft">
          {errorText}
        </span>
      ) : null}

      {stale && !running && !neverComputed ? (
        deferred ? (
          <span
            className="rounded-full bg-surface-muted px-2 py-0.5 font-medium text-ink-muted"
            title={t("report.deferredTitle")}
          >
            {t("report.deferred")}
          </span>
        ) : (
          <span className="rounded-full bg-warn-soft px-2 py-0.5 font-medium text-warn-ink">
            {t("report.stale")}
          </span>
        )
      ) : null}

      <button
        type="button"
        onClick={onRefresh}
        disabled={running}
        className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 font-medium text-ink-secondary transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
      >
        <RefreshCw className="h-3 w-3" aria-hidden="true" />
        {t("report.recompute")}
      </button>
    </div>
  );
}
