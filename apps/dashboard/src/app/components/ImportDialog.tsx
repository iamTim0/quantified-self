"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CalendarRange,
  CheckCircle2,
  History,
  Loader2,
  Minus,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  SkipForward,
  Upload,
  X,
  Zap,
} from "lucide-react";
import { apiFetch } from "../lib/api";
import { usePolling } from "../lib/polling";
import { useI18n, type Translate } from "../lib/i18n/provider";
import { uploadPercent, useUploads } from "../lib/uploads/provider";
import { messageForRun, type SyncRun } from "./import-run";

export type { SyncRun } from "./import-run";

/**
 * Import dialog with an explicit time range, a smart/force choice and a preview of
 * what the import would actually do.
 *
 * Previously "Sync Now" sent nothing but a source type: no range, no preview, no
 * way to backfill a specific period, and no indication that most of the requested
 * window was already present. Core now returns a plan, so the user sees which
 * ranges will be skipped and why before anything is queued.
 */

export interface ImportRange {
  start: string;
  end: string;
}

export interface ImportPlan {
  requested: ImportRange;
  covered_ranges: ImportRange[];
  missing_ranges: ImportRange[];
  recommended_range: ImportRange | null;
  skipped_ranges: ImportRange[];
  mode: "smart" | "force";
  reason: string;
  confidence: "high" | "low";
  window_reason?: string;
  total_points: number;
  docs_url?: string;
}

interface ImportDialogProps {
  apiBase: string;
  /** The connector instance. Every endpoint here addresses it by id. */
  sourceType: string;
  sourceName: string;
  /**
   * The connector's *type*, where an export file can be uploaded for it. The id
   * above says which connector; this says which importer knows how to read the
   * file, and it is the one part of the upload URL that is not an id.
   */
  providerType?: string;
  /** Whether this provider hands its users an export file at all. */
  fileImport?: boolean;
  /**
   * A push connector: data arrives when the phone sends it, so there is nothing
   * to trigger here. The dialog still opens — it is where progress and history
   * live, and a pushed import had nowhere to show either.
   */
  passive?: boolean;
  isOpen: boolean;
  onClose: () => void;
  onQueued?: () => void;
}

/** How often to refresh while an import is running. */
const PROGRESS_POLL_MS = 2000;

/** A run that has started and not finished. There is at most one per connector. */
function activeRun(runs: SyncRun[]): SyncRun | undefined {
  return runs.find((run) => run.finished_at === null && run.status !== "skipped");
}

/** "about 2 minutes", from seconds — or nothing when the connector has no history. */
function durationHint(t: Translate, seconds: number | null | undefined): string | null {
  if (!seconds || seconds <= 0) return null;
  if (seconds < 90) {
    return t("import.typicallySeconds", { count: Math.max(1, Math.round(seconds)) });
  }
  return t("import.typicallyMinutes", { count: Math.round(seconds / 60) });
}

/** `datetime-local` needs `YYYY-MM-DDTHH:mm` in local time, not an ISO UTC string. */
function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

function fromLocalInput(value: string): string {
  return new Date(value).toISOString();
}

/** A range in the reader's own locale, which `useI18n` knows and this file did not. */
function formatRange(formatDateTime: (value: string) => string, range: ImportRange): string {
  return `${formatDateTime(range.start)} – ${formatDateTime(range.end)}`;
}

function durationLabel(t: Translate, range: ImportRange): string {
  const ms = new Date(range.end).getTime() - new Date(range.start).getTime();
  const hours = ms / 3_600_000;
  if (hours < 48) return t("import.hours", { count: Math.max(1, Math.round(hours)) });
  return t("import.days", { count: Math.round(hours / 24) });
}

export default function ImportDialog({
  apiBase,
  sourceType,
  sourceName,
  providerType,
  fileImport = false,
  passive = false,
  isOpen,
  onClose,
  onQueued,
}: ImportDialogProps) {
  const { t, formatDateTime, formatNumber } = useI18n();
  const { jobFor, start: startUpload, cancel: cancelUpload, retry: retryUpload } = useUploads();
  const [mode, setMode] = useState<"smart" | "force">("smart");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [typicalSeconds, setTypicalSeconds] = useState<number | null>(null);
  const [planning, setPlanning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState("");

  // The upload itself is not this dialog's state: it runs above every screen so that
  // closing the dialog does not kill a transfer that takes minutes. What is left here
  // is which connector's upload to render.
  const upload = jobFor(sourceType);
  const uploading = upload?.phase === "uploading" || upload?.phase === "assembling";
  // Suppresses the "suggested range" hint once the user edits the pickers.
  const [rangeTouched, setRangeTouched] = useState(false);

  const authHeaders = useCallback(() => ({ "Content-Type": "application/json" }), []);

  /**
   * Ask Core what this import would do. With no range chosen yet, Core derives one
   * from the connector's poll interval and the last successful run, and we prefill
   * the pickers with it — the user can then adjust before importing.
   */
  const loadPlan = useCallback(
    async (withRange: boolean) => {
      setPlanning(true);
      setError("");
      try {
        const body: Record<string, unknown> = { mode };
        if (withRange && start && end) {
          body.start = fromLocalInput(start);
          body.end = fromLocalInput(end);
        }
        const res = await apiFetch(`${apiBase}/api/v1/data/sources/${sourceType}/import-plan`, {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          throw new Error(t("import.planFailed"));
        }
        const data: ImportPlan = await res.json();
        setPlan(data);
        if (!withRange) {
          setStart(toLocalInput(data.requested.start));
          setEnd(toLocalInput(data.requested.end));
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setPlan(null);
      } finally {
        setPlanning(false);
      }
    },
    [apiBase, authHeaders, mode, sourceType, start, end],
  );

  const loadRuns = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/sources/${sourceType}/sync-runs?limit=5`, {
        headers: authHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setRuns(data.runs || []);
        setTypicalSeconds(data.typical_duration_seconds ?? null);
      }
    } catch {
      // History is informational; a failure here must not block the import.
    }
  }, [apiBase, authHeaders, sourceType]);

  // The parent mounts this component fresh per connector (see the `key` it passes),
  // so there is no stale state to reset here — only the initial loads to kick off.
  //
  // The work is deferred past the synchronous effect body on purpose: calling
  // loadPlan inline would flip the loading flag during the effect and trigger a
  // cascading render. The cancellation flag stops a slow response from writing
  // state after the dialog has been closed.
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    void (async () => {
      await Promise.resolve();
      if (cancelled) return;
      await loadPlan(false);
      if (!cancelled) await loadRuns();
    })();

    return () => {
      cancelled = true;
    };
    // Only re-run when the dialog opens for a different connector.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, sourceType]);

  // Re-plan when the user changes the mode or edits the range.
  useEffect(() => {
    if (!isOpen || !start || !end) return;
    const timer = setTimeout(() => loadPlan(true), 350);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, start, end]);

  // While a run is in flight, keep asking. The counts are written by the ingest
  // consumer as the data actually lands, so this is the import's real progress
  // rather than a client-side animation. Polling stops the moment nothing is
  // running, so an idle dialog costs nothing.
  const running = activeRun(runs);
  const typicalHint = durationHint(t, typicalSeconds);
  usePolling(() => void loadRuns(), isOpen && running ? PROGRESS_POLL_MS : null);

  /**
   * Hand the archive to the upload that runs above this dialog.
   *
   * It goes out in parts rather than as one request body, because the hops in between
   * refuse a body the size an export reaches — a 200 MB Apple Health export was
   * rejected by Cloudflare's edge at 100 MB, after about 2 % had been sent. The parts
   * are reassembled by the importer; see `lib/uploads/provider.tsx`.
   *
   * Nothing is awaited here: the transfer belongs to the provider from this point, so
   * the dialog can be minimised or closed and the banner keeps showing it.
   */
  const handleUpload = () => {
    if (!file || !providerType) return;
    setError("");
    setResult("");
    startUpload({
      apiBase,
      sourceId: sourceType,
      sourceName,
      providerType,
      file,
    });
    setFile(null);
  };

  // An accepted archive is the moment the connector has something new to say: the
  // importer opened a run, and that is what the progress panel follows. Only the
  // fetches live in the effect — that the upload finished is already in the job, so
  // copying it into local state here would be a second source of the same truth.
  useEffect(() => {
    if (upload?.phase !== "done") return;
    let cancelled = false;

    // Deferred past the synchronous effect body for the same reason the initial load
    // above is: `loadRuns` sets state, and doing that during the effect triggers a
    // cascading render.
    void (async () => {
      await Promise.resolve();
      if (cancelled) return;
      onQueued?.();
      await loadRuns();
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [upload?.phase, upload?.id]);

  const handleImport = async () => {
    setSubmitting(true);
    setError("");
    setResult("");
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/sources/sync`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          source_id: sourceType,
          mode,
          start: start ? fromLocalInput(start) : undefined,
          end: end ? fromLocalInput(end) : undefined,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || data?.status === "error") throw new Error(t("import.startFailed"));

      setResult(data?.status === "skipped" ? t("import.nothingToDo") : t("import.queued"));
      onQueued?.();
      loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (!isOpen) return null;

  const nothingToDo = plan !== null && plan.recommended_range === null;
  const effective = plan?.recommended_range;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-3xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <div className="flex items-center gap-2.5">
            <CalendarRange className="h-5 w-5 text-[#0d5c3a]" />
            <div>
              <h2 className="text-base font-bold text-slate-900">
                {t("import.title", { name: sourceName })}
              </h2>
              <p className="text-[11px] text-slate-500">{t("import.subtitle")}</p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {/*
              Offered only while something is uploading, because that is the only time
              the distinction exists: closing this dialog has never stopped an import,
              and now it does not stop an upload either. The button says so, so that a
              user with a 200 MB archive does not sit and watch it.
            */}
            {uploading && (
              <button
                onClick={onClose}
                aria-label={t("import.minimize")}
                title={t("import.minimizeHint")}
                className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                <Minus className="h-5 w-5" />
              </button>
            )}
            <button
              onClick={onClose}
              aria-label={t("import.close")}
              className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="space-y-5 px-6 py-5">
          {/*
            A push connector has nothing to trigger: the phone decides when data
            arrives. Everything that plans or starts an import is hidden, and what
            remains is what such a connector does have — progress and history.
          */}
          {passive && (
            <p className="rounded-2xl border border-violet-200 bg-violet-50 px-3.5 py-2.5 text-[11px] leading-relaxed text-violet-900">
              {t("import.passiveExplainer")}
            </p>
          )}

          {/*
            The export file. Offered for every connector whose provider hands one
            out, whether or not it is also connected to an API: an archive is how
            you get the years that predate the connector, and it lands in the same
            connector, so a reading that is already stored stays one reading.
          */}
          {fileImport && providerType && (
            <div className="rounded-2xl border border-sky-200 bg-sky-50/70 p-4">
              <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-sky-900">
                <Upload className="h-3.5 w-3.5" /> {t("import.uploadLegend")}
              </h3>
              <p className="mt-1 text-[11px] leading-relaxed text-sky-900">
                {t(
                  providerType === "apple_health"
                    ? "import.uploadHintAppleHealth"
                    : "import.uploadHintWhoop",
                )}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <input
                  type="file"
                  accept=".zip,application/zip"
                  aria-label={t("import.uploadChoose")}
                  disabled={uploading}
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="min-w-0 flex-1 text-[11px] text-slate-600 file:mr-3 file:rounded-xl file:border-0 file:bg-white file:px-3 file:py-2 file:text-[11px] file:font-bold file:text-sky-900 disabled:opacity-50"
                />
                <button
                  onClick={handleUpload}
                  disabled={!file || uploading}
                  className="flex items-center gap-2 whitespace-nowrap rounded-2xl bg-sky-900 px-4 py-2 text-xs font-bold text-white transition-colors hover:bg-sky-950 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {uploading ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Upload className="h-3.5 w-3.5" />
                  )}
                  {uploading ? t("import.uploading") : t("import.uploadStart")}
                </button>
              </div>

              {/*
                The upload, however this dialog was opened. It is rendered from the
                provider rather than from local state, so reopening the dialog on a
                transfer that is already running shows where it has got to instead of
                an empty file picker.
              */}
              {upload?.phase === "done" && (
                <p className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11px] text-emerald-800">
                  {t("import.uploadAccepted")}
                </p>
              )}

              {upload && upload.phase !== "done" && (
                <div className="mt-3" aria-label={t("import.uploadProgress")}>
                  <div className="mb-1 flex items-center justify-between gap-2 text-[11px] text-sky-900">
                    <span className="truncate" title={upload.fileName}>
                      {upload.fileName}
                    </span>
                    {(upload.phase === "uploading" || upload.phase === "assembling") && (
                      <span className="shrink-0 tabular-nums">
                        {formatNumber(uploadPercent(upload))}%
                      </span>
                    )}
                  </div>
                  <div
                    className="h-2 w-full overflow-hidden rounded-full bg-sky-100"
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={uploadPercent(upload)}
                    aria-valuetext={t("import.uploadProgressPercent", {
                      percent: formatNumber(uploadPercent(upload)),
                    })}
                  >
                    <div
                      className="h-full rounded-full bg-sky-600 transition-[width] duration-200"
                      style={{ width: `${uploadPercent(upload)}%` }}
                    />
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[11px] text-sky-900">
                      {upload.phase === "assembling" && t("upload.assembling")}
                      {upload.phase === "uploading" && t("import.uploadInParts")}
                      {upload.phase === "cancelled" && t("upload.cancelledBody")}
                      {upload.phase === "error" && t("import.uploadFailed")}
                    </span>
                    {uploading && (
                      <button
                        onClick={() => cancelUpload(upload.id)}
                        className="rounded-xl px-2.5 py-1 text-[11px] font-bold text-red-700 hover:bg-red-50"
                      >
                        {t("upload.cancel")}
                      </button>
                    )}
                    {upload.phase === "error" && upload.resumable && (
                      <button
                        onClick={() => retryUpload(upload.id)}
                        className="flex items-center gap-1.5 rounded-xl bg-slate-900 px-2.5 py-1 text-[11px] font-bold text-white hover:bg-slate-800"
                      >
                        <RotateCcw className="h-3 w-3" /> {t("upload.resume")}
                      </button>
                    )}
                  </div>
                </div>
              )}

              <p className="mt-2 text-[11px] text-sky-800">{t("import.uploadReimportNote")}</p>
            </div>
          )}

          {!passive && (
            <>
              {/* Range */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-slate-500">
                    {t("import.from")}
                  </span>
                  <input
                    type="datetime-local"
                    value={start}
                    onChange={(e) => {
                      setStart(e.target.value);
                      setRangeTouched(true);
                    }}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 outline-none focus-visible:border-[#0d5c3a]"
                  />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-slate-500">
                    {t("import.to")}
                  </span>
                  <input
                    type="datetime-local"
                    value={end}
                    onChange={(e) => {
                      setEnd(e.target.value);
                      setRangeTouched(true);
                    }}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 outline-none focus-visible:border-[#0d5c3a]"
                  />
                </label>
              </div>

              {plan?.window_reason && !rangeTouched && (
                <p className="text-[11px] leading-relaxed text-slate-500">
                  <span className="font-semibold text-slate-600">{t("import.suggestion")}</span>{" "}
                  {t("import.windowSuggested")}
                </p>
              )}

              {/* Mode */}
              <fieldset className="space-y-2">
                <legend className="mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">
                  {t("import.modeLegend")}
                </legend>
                <label
                  className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-3.5 ${
                    mode === "smart"
                      ? "border-[#0d5c3a] bg-emerald-50/60"
                      : "border-slate-200 bg-white"
                  }`}
                >
                  <input
                    type="radio"
                    name="import-mode"
                    checked={mode === "smart"}
                    onChange={() => setMode("smart")}
                    className="mt-0.5"
                  />
                  <span>
                    <span className="flex items-center gap-1.5 text-sm font-bold text-slate-900">
                      <ShieldCheck className="h-4 w-4 text-[#0d5c3a]" /> {t("import.smartLabel")}
                    </span>
                    <span className="mt-0.5 block text-[11px] leading-relaxed text-slate-600">
                      {t("import.smartHint")}
                    </span>
                  </span>
                </label>

                <label
                  className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-3.5 ${
                    mode === "force"
                      ? "border-amber-500 bg-amber-50/60"
                      : "border-slate-200 bg-white"
                  }`}
                >
                  <input
                    type="radio"
                    name="import-mode"
                    checked={mode === "force"}
                    onChange={() => setMode("force")}
                    className="mt-0.5"
                  />
                  <span>
                    <span className="flex items-center gap-1.5 text-sm font-bold text-slate-900">
                      <Zap className="h-4 w-4 text-amber-600" /> {t("import.forceLabel")}
                    </span>
                    <span className="mt-0.5 block text-[11px] leading-relaxed text-slate-600">
                      {t("import.forceBody")}
                    </span>
                  </span>
                </label>
              </fieldset>

              {mode === "force" && (
                <div className="flex gap-2.5 rounded-2xl border border-amber-200 bg-amber-50 p-3.5">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                  <p className="text-[11px] leading-relaxed text-amber-900">
                    {t("import.forceWarning")} {t("import.forceHint")}
                  </p>
                </div>
              )}
            </>
          )}

          {/*
            Live progress. The counts come from the ingest consumer as the data is
            actually stored, so this is what happened rather than an animation. A
            percentage appears only where the total is genuinely known — a file
            upload knows it after parsing, a provider poll does not — and where it
            is not, the count is shown on its own. An invented percentage would be
            worse than an honest number.
          */}
          {running && (
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 p-4">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-emerald-800">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />{" "}
                  {running.status === "loading" ? t("import.loadingCore") : t("import.running")}
                </h3>
                {typicalHint && <span className="text-[11px] text-emerald-700">{typicalHint}</span>}
              </div>

              {(running.points_expected ?? running.points_received) > 0 ? (
                <>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-emerald-100">
                    <div
                      className="h-full rounded-full bg-[#0d5c3a] transition-colors"
                      style={{
                        width: `${Math.min(
                          100,
                          Math.round(
                            (running.points_processed /
                              (running.points_expected ?? running.points_received)) *
                              100,
                          ),
                        )}%`,
                      }}
                    />
                  </div>
                  <p className="mt-1.5 text-[11px] text-emerald-900">
                    {t("import.progressOf", {
                      done: running.points_processed,
                      total: running.points_expected ?? running.points_received,
                    })}
                  </p>
                </>
              ) : (
                <p className="text-[11px] text-emerald-900">
                  {t("import.progressCounted", { count: running.points_processed })}
                </p>
              )}
            </div>
          )}

          {/* Plan preview — only meaningful where an import can be planned. */}
          {!passive && (
            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                  {t("import.previewLegend")}
                </h3>
                {planning && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />}
              </div>

              {!plan && !planning && (
                <p className="text-xs text-slate-500">{t("import.noAnalysis")}</p>
              )}

              {plan && (
                <div className="space-y-2.5">
                  <p className="text-xs leading-relaxed text-slate-700">{plan.reason}</p>

                  {plan.confidence === "low" && (
                    <p className="rounded-xl bg-slate-100 px-3 py-2 text-[11px] text-slate-600">
                      {t("import.tooIrregular")}
                    </p>
                  )}

                  {plan.skipped_ranges.length > 0 && (
                    <div>
                      <p className="mb-1 flex items-center gap-1.5 text-[11px] font-bold text-slate-600">
                        <SkipForward className="h-3.5 w-3.5" /> {t("import.willSkip")}
                      </p>
                      <ul className="space-y-1">
                        {plan.skipped_ranges.map((r) => (
                          <li
                            key={`${r.start}-${r.end}`}
                            className="flex items-center justify-between rounded-lg bg-white px-2.5 py-1.5 text-[11px] text-slate-600"
                          >
                            <span className="font-mono">{formatRange(formatDateTime, r)}</span>
                            <span className="text-slate-400">{durationLabel(t, r)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {effective ? (
                    <div>
                      <p className="mb-1 flex items-center gap-1.5 text-[11px] font-bold text-[#0d5c3a]">
                        <RefreshCw className="h-3.5 w-3.5" /> {t("import.willImport")}
                      </p>
                      <div className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[11px] text-emerald-900">
                        <span className="font-mono">{formatRange(formatDateTime, effective)}</span>
                        <span>{durationLabel(t, effective)}</span>
                      </div>
                    </div>
                  ) : (
                    <p className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-700">
                      <CheckCircle2 className="h-3.5 w-3.5" /> {t("import.nothingToImportShort")}
                    </p>
                  )}

                  {plan.docs_url && (
                    <a
                      href={plan.docs_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-block text-[11px] text-[#0d5c3a] underline"
                    >
                      {t("import.howItWorks")}
                    </a>
                  )}
                </div>
              )}
            </div>
          )}

          {/* History */}
          {runs.length > 0 && (
            <details className="rounded-2xl border border-slate-200 bg-white p-4">
              <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">
                <History className="h-3.5 w-3.5" /> {t("import.recent", { count: runs.length })}
              </summary>
              <ul className="mt-3 space-y-2">
                {runs.map((run) => (
                  <li key={run.id} className="rounded-xl bg-slate-50 px-3 py-2 text-[11px]">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-700">
                        {formatDateTime(run.started_at)}
                      </span>
                      <span className="flex items-center gap-1.5">
                        {run.mode === "force" && (
                          <span className="rounded bg-amber-100 px-1.5 py-0.5 font-bold text-amber-800">
                            force
                          </span>
                        )}
                        <span className="text-slate-500">{run.status}</span>
                      </span>
                    </div>
                    <p className="mt-0.5 text-slate-500">
                      {t("import.runCounts", {
                        accepted: run.points_accepted,
                        duplicate: run.points_duplicate,
                        rejected: run.points_rejected ?? 0,
                        unsupported: run.unsupported_fields ?? 0,
                      })}
                    </p>
                    {messageForRun(t, run) && (
                      <p className="mt-0.5 text-slate-400">{messageForRun(t, run)}</p>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {error && (
            <p className="rounded-2xl border border-red-200 bg-red-50 px-3.5 py-2.5 text-xs text-red-700">
              {error}
            </p>
          )}
          {result && (
            <p className="rounded-2xl border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-xs text-emerald-800">
              {result}
            </p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2.5 border-t border-slate-100 px-6 py-4">
          <button
            onClick={onClose}
            className="rounded-2xl px-4 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-100"
          >
            {passive ? t("common.close") : t("common.cancel")}
          </button>
          {!passive && (
            <button
              onClick={handleImport}
              disabled={submitting || planning || (nothingToDo && mode === "smart")}
              className="flex items-center gap-2 rounded-2xl bg-[#0d5c3a] px-5 py-2.5 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              {nothingToDo && mode === "smart" ? t("import.nothingToImport") : t("import.start")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
