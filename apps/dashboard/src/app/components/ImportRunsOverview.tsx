"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Clock3, Loader2, RefreshCw, XCircle } from "lucide-react";
import { apiFetch } from "../lib/api";
import { usePolling } from "../lib/polling";
import { useI18n } from "../lib/i18n/provider";
import {
  ACTIVE_STATUSES,
  messageForRun,
  statusClass,
  statusKey,
  triggerKey,
  type SyncRun,
} from "./import-run";

interface ImportRunsOverviewProps {
  apiBase: string;
  tenantId: string;
  refreshTrigger: number;
}

export default function ImportRunsOverview({
  apiBase,
  tenantId,
  refreshTrigger,
}: ImportRunsOverviewProps) {
  const { t, formatDateTime, formatNumber } = useI18n();
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);

  const loadRuns = useCallback(
    async (append = false, offset = 0) => {
      try {
        const response = await apiFetch(
          `${apiBase}/api/v1/data/sync-runs?limit=50&offset=${append ? offset : 0}`,
          { headers: { "X-Tenant-ID": tenantId }, cache: "no-store" },
        );
        if (!response.ok) {
          setError(true);
          return;
        }
        const data = await response.json();
        setRuns((previous) => (append ? [...previous, ...(data.runs || [])] : data.runs || []));
        setHasMore(Boolean(data.has_more));
        setError(false);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [apiBase, tenantId],
  );

  useEffect(() => {
    if (!tenantId) return;
    void loadRuns();
  }, [loadRuns, refreshTrigger, tenantId]);

  const active = useMemo(() => runs.filter((run) => ACTIVE_STATUSES.has(run.status)), [runs]);
  const loadingInCore = active.filter((run) => run.status === "loading").length;
  const completed = runs.filter((run) => run.status === "success").length;
  const failed = runs.filter((run) => run.status === "error").length;

  usePolling(() => void loadRuns(), tenantId ? (active.length > 0 ? 2500 : 10000) : null);

  return (
    <section className="space-y-4 rounded-3xl border border-slate-200/80 bg-white p-6 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Clock3 className="h-4 w-4 text-[#0d5c3a]" />
            <h2 className="text-sm font-bold text-slate-900">{t("importOverview.title")}</h2>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">
            {t("importOverview.subtitle")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadRuns()}
          className="inline-flex items-center gap-2 self-start rounded-2xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          aria-label={t("importOverview.refresh")}
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          {t("importOverview.refresh")}
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <OverviewCount label={t("importOverview.active")} value={active.length} tone="active" />
        <OverviewCount
          label={t("importOverview.loadingCore")}
          value={loadingInCore}
          tone="loading"
        />
        <OverviewCount label={t("importOverview.completed")} value={completed} tone="success" />
        <OverviewCount label={t("importOverview.failed")} value={failed} tone="error" />
      </div>

      {error && <p className="text-xs text-rose-700">{t("importOverview.loadFailed")}</p>}
      {!error && loading && runs.length === 0 && (
        <p className="py-4 text-center text-xs text-slate-400">{t("importOverview.loading")}</p>
      )}
      {!error && !loading && runs.length === 0 && (
        <p className="py-4 text-center text-xs text-slate-500">{t("importOverview.empty")}</p>
      )}

      {runs.length > 0 && (
        <div className="space-y-2">
          {runs.map((run) => {
            const isActive = ACTIVE_STATUSES.has(run.status);
            const expected = run.points_expected ?? run.points_received;
            const progress =
              expected > 0
                ? Math.min(100, Math.round((run.points_processed / expected) * 100))
                : null;
            return (
              <article
                key={run.id}
                className="rounded-2xl border border-slate-200 bg-slate-50/60 p-3.5"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      {isActive ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-600" />
                      ) : run.status === "success" ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                      ) : run.status === "error" ? (
                        <XCircle className="h-3.5 w-3.5 text-rose-600" />
                      ) : (
                        <Clock3 className="h-3.5 w-3.5 text-slate-500" />
                      )}
                      <span className="truncate text-xs font-bold text-slate-900">
                        {run.connector_name || run.source_type}
                      </span>
                      <span className="text-[10px] uppercase tracking-wide text-slate-400">
                        {run.source_type}
                      </span>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase ${statusClass(run.status)}`}
                      >
                        {t(statusKey(run.status))}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
                      <span>{t(triggerKey(run.trigger))}</span>
                      <span>
                        {run.started_at
                          ? formatDateTime(run.started_at)
                          : t("importerDetail.unknown")}
                      </span>
                      <span>
                        {t("importOverview.progress", {
                          processed: formatNumber(run.points_processed),
                          total:
                            run.points_expected === null
                              ? t("importerDetail.unknown")
                              : formatNumber(run.points_expected),
                        })}
                      </span>
                    </div>
                    {(run.points_rejected > 0 || run.unsupported_fields > 0) && (
                      <p className="mt-1 text-[11px] text-amber-700">
                        {t("importOverview.quality", {
                          rejected: formatNumber(run.points_rejected ?? 0),
                          unsupported: formatNumber(run.unsupported_fields ?? 0),
                        })}
                      </p>
                    )}
                  </div>
                  {progress !== null && isActive && (
                    <span className="shrink-0 text-[11px] font-semibold text-slate-600">
                      {progress}%
                    </span>
                  )}
                </div>
                {progress !== null && isActive && (
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200">
                    <div
                      className="h-full rounded-full bg-[#0d5c3a] transition-all"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                )}
                {messageForRun(t, run) && (
                  <p className="mt-2 break-words text-[11px] text-slate-500">
                    {messageForRun(t, run)}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      )}

      {hasMore && (
        <button
          type="button"
          onClick={() => {
            setLoadingMore(true);
            void loadRuns(true, runs.length);
          }}
          disabled={loadingMore}
          className="flex w-full items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          {loadingMore && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {loadingMore ? t("importOverview.loadingMore") : t("importOverview.loadMore")}
        </button>
      )}
    </section>
  );
}

function OverviewCount({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "active" | "loading" | "success" | "error";
}) {
  const color =
    tone === "success"
      ? "text-emerald-700"
      : tone === "error"
        ? "text-rose-700"
        : tone === "loading"
          ? "text-sky-700"
          : "text-amber-700";
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-3 py-2.5">
      <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-1 text-lg font-extrabold ${color}`}>{value}</p>
    </div>
  );
}
