"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  Clock3,
  History,
  Loader2,
  RefreshCw,
  Settings,
  XCircle,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { apiFetch } from "../lib/api";
import { usePolling } from "../lib/polling";
import { useI18n } from "../lib/i18n/provider";
import { getConnectorDirection } from "./ConnectorModal";
import ImportDialog from "./ImportDialog";
import ConnectorDataQuality from "./ConnectorDataQuality";
import OperatorRunDiagnostics from "./OperatorRunDiagnostics";
import type { ConnectorItem } from "./ConnectorsPage";
import {
  durationLabel,
  messageForRun,
  modeKey,
  statusClass,
  statusKey,
  triggerKey,
  type SyncRun,
} from "./import-run";

interface ImporterDetailPageProps {
  apiBase: string;
  tenantId: string;
  connector: ConnectorItem;
  refreshTrigger: number;
  userRole: string;
  onOpenConfigureModal: (connector: ConnectorItem) => void;
}

const RUN_REFRESH_MS = 5_000;

export default function ImporterDetailPage({
  apiBase,
  tenantId,
  connector,
  refreshTrigger,
  userRole,
  onOpenConfigureModal,
}: ImporterDetailPageProps) {
  const router = useRouter();
  const { t, formatDateTime, formatNumber } = useI18n();
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [typicalSeconds, setTypicalSeconds] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [importOpen, setImportOpen] = useState(false);

  const loadRuns = useCallback(
    async (append = false, offset = 0) => {
      try {
        const response = await apiFetch(
          `${apiBase}/api/v1/data/sources/${connector.id}/sync-runs?limit=100&offset=${append ? offset : 0}`,
          { headers: { "X-Tenant-ID": tenantId }, cache: "no-store" },
        );
        if (!response.ok) {
          setError(t("importerDetail.historyFailed"));
          return;
        }
        const data = await response.json();
        setRuns((previous) => (append ? [...previous, ...(data.runs || [])] : data.runs || []));
        setTypicalSeconds(data.typical_duration_seconds ?? null);
        setHasMore(Boolean(data.has_more));
        setError("");
      } catch {
        setError(t("importerDetail.historyFailed"));
      } finally {
        setLoading(false);
      }
    },
    [apiBase, connector.id, t, tenantId],
  );

  useEffect(() => {
    void loadRuns();
  }, [loadRuns, refreshTrigger]);

  usePolling(() => void loadRuns(), RUN_REFRESH_MS);

  const loadMore = async () => {
    setLoadingMore(true);
    await loadRuns(true, runs.length);
    setLoadingMore(false);
  };

  const counts = useMemo(
    () => ({
      success: runs.filter((run) => run.status === "success").length,
      error: runs.filter((run) => run.status === "error").length,
      active: runs.filter((run) => run.finished_at === null).length,
    }),
    [runs],
  );

  const passive = getConnectorDirection(connector.source_type) === "passive";
  const fileOnly = connector.import_mode === "file";
  /*
    Same reasoning as the connectors list: a passive connector has nothing to
    trigger, so the dialog held nothing but a run history for it — and this page
    is that history, in full, below. The action survives only where the dialog
    can still do something, which is uploading an export archive.
  */
  const pushOnly = passive || fileOnly;
  const uploadOnly = pushOnly && (fileOnly || Boolean(connector.supports_file_import));
  const latest = runs[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <button
            type="button"
            onClick={() => router.push("/connectors")}
            aria-label={t("importerDetail.back")}
            className="mt-1 rounded-xl border border-line bg-surface p-2 text-ink-muted shadow-sm hover:bg-page"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-ink-muted">
              {t("importerDetail.eyebrow")}
            </p>
            <h1 className="text-3xl font-extrabold tracking-tight text-ink">
              {connector.display_name || connector.source_type}
            </h1>
            <p className="mt-1 text-xs text-ink-muted">
              {connector.source_type} · {passive ? t("connectors.passive") : t("connectors.active")}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void loadRuns()}
            className="inline-flex items-center gap-2 rounded-2xl border border-line bg-surface px-3.5 py-2 text-xs font-semibold text-ink-secondary shadow-sm hover:bg-page"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            {t("header.refresh")}
          </button>
          <button
            type="button"
            onClick={() => onOpenConfigureModal(connector)}
            className="inline-flex items-center gap-2 rounded-2xl bg-brand px-3.5 py-2 text-xs font-bold text-brand-ink shadow-md shadow-brand/20 hover:bg-brand-hover"
          >
            <Settings className="h-3.5 w-3.5" />
            {t("connectors.edit")}
          </button>
          {(!pushOnly || uploadOnly) && (
            <button
              type="button"
              onClick={() => setImportOpen(true)}
              className="inline-flex items-center gap-2 rounded-2xl border border-line bg-surface px-3.5 py-2 text-xs font-semibold text-ink-secondary hover:bg-page"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {uploadOnly ? t("connectors.upload") : t("connectors.import")}
            </button>
          )}
        </div>
      </div>

      {error && (
        <p className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-xs text-rose-800 dark:border-rose-900/70 dark:bg-rose-950/40 dark:text-rose-200">
          {error}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <SummaryCard label={t("importerDetail.totalRuns")} value={formatNumber(runs.length)} />
        <SummaryCard
          label={t("importerDetail.successfulRuns")}
          value={formatNumber(counts.success)}
          tone="success"
        />
        <SummaryCard
          label={t("importerDetail.failedRuns")}
          value={formatNumber(counts.error)}
          tone="error"
        />
        <SummaryCard
          label={t("importerDetail.activeRuns")}
          value={formatNumber(counts.active)}
          tone="active"
        />
        <SummaryCard
          label={t("importerDetail.typicalDuration")}
          value={durationLabel(t, formatNumber, typicalSeconds)}
        />
      </div>

      {latest && (
        <section className="rounded-3xl border border-line bg-surface p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <Clock3 className="h-4 w-4 text-brand" />
            <h2 className="text-sm font-bold text-ink">
              {t("importerDetail.latestRun")}
            </h2>
          </div>
          <div className="grid gap-3 text-xs sm:grid-cols-4">
            <DetailValue label={t("importerDetail.status")} value={t(statusKey(latest.status))} />
            <DetailValue
              label={t("importerDetail.trigger")}
              value={t(triggerKey(latest.trigger))}
            />
            <DetailValue
              label={t("importerDetail.started")}
              value={formatDateTime(latest.started_at)}
            />
            <DetailValue
              label={t("importerDetail.duration")}
              value={durationLabel(t, formatNumber, latest.duration_seconds)}
            />
          </div>
          {messageForRun(t, latest) && (
            <p className="mt-3 rounded-2xl bg-page px-3 py-2 text-xs text-ink-muted">
              {messageForRun(t, latest)}
            </p>
          )}
          <OperatorRunDiagnostics
            run={latest}
            userRole={userRole}
            typicalSeconds={typicalSeconds}
          />
        </section>
      )}

      {/* This connector's own data-quality decisions.
          They used to sit on `/quality` as if they were a property of the
          workspace. They are not: every row carries this connector's
          `source_id`, and the run history right below has been counting
          `unsupported_fields` per run with nowhere to click through to what
          they were. */}
      <ConnectorDataQuality apiBase={apiBase} sourceId={connector.id} />

      <section className="rounded-3xl border border-line bg-surface p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-brand" />
            <h2 className="text-sm font-bold text-ink">
              {t("importerDetail.historyTitle")}
            </h2>
          </div>
          <span className="text-[11px] text-ink-muted">
            {t("importerDetail.autoRefresh", { seconds: RUN_REFRESH_MS / 1000 })}
          </span>
        </div>

        {loading && runs.length === 0 ? (
          <div className="flex items-center justify-center gap-2 py-12 text-xs text-ink-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> {t("importerDetail.loading")}
          </div>
        ) : runs.length === 0 ? (
          <p className="rounded-2xl bg-page px-4 py-8 text-center text-xs text-ink-muted">
            {t("importerDetail.noRuns")}
          </p>
        ) : (
          <div className="space-y-3">
            {runs.map((run) => (
              <article
                key={run.id}
                className="rounded-2xl border border-line bg-page p-4"
              >
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="flex min-w-0 items-start gap-2.5">
                    {run.status === "success" ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" />
                    ) : run.status === "error" ? (
                      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger-ink-on-soft" />
                    ) : (
                      <Clock3 className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
                    )}
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase ${statusClass(run.status)}`}
                        >
                          {t(statusKey(run.status))}
                        </span>
                        <span className="text-[11px] font-semibold text-ink-secondary">
                          {t(triggerKey(run.trigger))}
                        </span>
                        <span className="text-[11px] text-ink-muted">
                          {formatDateTime(run.started_at)}
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] text-ink-muted">
                        {t("importerDetail.points", {
                          processed: formatNumber(run.points_processed),
                          accepted: formatNumber(run.points_accepted),
                          duplicate: formatNumber(run.points_duplicate),
                          rejected: formatNumber(run.points_rejected ?? 0),
                          unsupported: formatNumber(run.unsupported_fields ?? 0),
                          expected:
                            run.points_expected === null
                              ? t("importerDetail.unknown")
                              : formatNumber(run.points_expected),
                        })}
                      </p>
                      {run.provider_window_start && run.provider_window_end && (
                        <p className="mt-1 text-[11px] text-ink-muted">
                          {t("importerDetail.providerWindow", {
                            start: formatDateTime(run.provider_window_start),
                            end: formatDateTime(run.provider_window_end),
                          })}
                        </p>
                      )}
                      {run.backlog_at_end !== null && run.backlog_at_end !== undefined && (
                        <p className="mt-1 text-[11px] text-ink-muted">
                          {t("importerDetail.backlog", {
                            count: formatNumber(run.backlog_at_end),
                          })}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-x-5 gap-y-1 text-[11px] text-ink-muted sm:grid-cols-4 lg:min-w-[430px]">
                    <DetailValue label={t("importerDetail.mode")} value={t(modeKey(run.mode))} />
                    <DetailValue
                      label={t("importerDetail.duration")}
                      value={durationLabel(t, formatNumber, run.duration_seconds)}
                    />
                    <DetailValue
                      label={t("importerDetail.finished")}
                      value={formatDateTime(run.finished_at)}
                    />
                    <DetailValue
                      label={t("importerDetail.requestId")}
                      value={run.request_id ?? "—"}
                      mono
                    />
                  </div>
                </div>
                {messageForRun(t, run) && (
                  <p className="mt-3 break-words border-t border-line pt-3 text-xs text-ink-muted">
                    {messageForRun(t, run)}
                  </p>
                )}
                <OperatorRunDiagnostics
                  run={run}
                  userRole={userRole}
                  typicalSeconds={typicalSeconds}
                />
              </article>
            ))}
            {hasMore && (
              <button
                type="button"
                onClick={() => void loadMore()}
                disabled={loadingMore}
                className="flex w-full items-center justify-center gap-2 rounded-2xl border border-line bg-surface px-4 py-3 text-xs font-semibold text-ink-secondary hover:bg-page disabled:opacity-50"
              >
                {loadingMore && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {loadingMore ? t("importerDetail.loadingMore") : t("importerDetail.loadMore")}
              </button>
            )}
          </div>
        )}
      </section>

      {importOpen && (
        <ImportDialog
          key={connector.id}
          apiBase={apiBase}
          sourceType={connector.id}
          sourceName={connector.display_name || connector.source_type}
          providerType={connector.source_type}
          fileImport={Boolean(connector.supports_file_import)}
          passive={pushOnly}
          isOpen
          onClose={() => setImportOpen(false)}
          onQueued={loadRuns}
        />
      )}
    </div>
  );
}

function SummaryCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "success" | "error" | "active";
}) {
  const valueClass =
    tone === "success"
      ? "text-ok-ink"
      : tone === "error"
        ? "text-danger-ink-on-soft"
        : tone === "active"
          ? "text-warn-ink"
          : "text-ink";
  return (
    <div className="rounded-2xl border border-line bg-surface p-4 shadow-sm">
      <p className="text-[10px] font-bold uppercase tracking-wider text-ink-muted">{label}</p>
      <p className={`mt-2 text-lg font-extrabold ${valueClass}`}>{value}</p>
    </div>
  );
}

function DetailValue({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] font-bold uppercase tracking-wider text-ink-muted">{label}</p>
      <p className={`mt-0.5 truncate text-[11px] text-ink-secondary ${mono ? "font-mono" : ""}`}>
        {value}
      </p>
    </div>
  );
}
