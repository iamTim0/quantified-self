"use client";

/**
 * What a minimised upload looks like.
 *
 * The import dialog can be closed while an archive is still going out — the upload
 * lives in `UploadProvider`, not in the dialog — and this is what keeps saying so.
 * One card per connector, on every screen, because the answer to "is it still
 * running?" should not require finding the dialog again.
 *
 * It covers the upload only. Once the importer has the archive, what matters is the
 * import, and that has a progress panel of its own on the connector.
 */

import React from "react";
import { AlertTriangle, CheckCircle2, Loader2, RotateCcw, Upload, X } from "lucide-react";

import { useI18n } from "../lib/i18n/provider";
import { uploadPercent, useUploads, type UploadJob } from "../lib/uploads/provider";

/** Megabytes, in the reader's own number formatting. */
function megabytes(
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string,
  bytes: number,
): string {
  return formatNumber(bytes / (1024 * 1024), { maximumFractionDigits: 1 });
}

export default function UploadBanner() {
  const { t, formatNumber } = useI18n();
  const { jobs, cancel, retry, dismiss } = useUploads();

  if (jobs.length === 0) return null;

  return (
    // `--tabbar-h` rather than a hand-copied `4.5rem`: this offset only has to
    // clear the tab bar, and a constant that restates another component's height
    // is correct exactly until that component changes.
    <div className="pointer-events-none fixed bottom-[calc(var(--tabbar-h)+env(safe-area-inset-bottom)+0.5rem)] right-[max(1rem,env(safe-area-inset-right))] z-40 md:bottom-4 flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2">
      {jobs.map((job) => (
        <article
          key={job.id}
          className="pointer-events-auto rounded-2xl border border-line bg-surface p-3.5 shadow-lg"
          aria-live="polite"
        >
          <Header
            job={job}
            t={t}
            onCancel={() => cancel(job.id)}
            onDismiss={() => dismiss(job.id)}
          />

          {(job.phase === "uploading" || job.phase === "assembling") && (
            <>
              <div
                className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-muted"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={uploadPercent(job)}
                aria-valuetext={t("upload.progressPercent", {
                  percent: formatNumber(uploadPercent(job)),
                })}
              >
                <div
                  className="h-full rounded-full bg-sky-600 transition-[width] duration-200"
                  style={{ width: `${uploadPercent(job)}%` }}
                />
              </div>
              <p className="mt-1.5 text-[11px] text-ink-muted">
                {job.phase === "assembling"
                  ? t("upload.assembling")
                  : t("upload.sentOf", {
                      done: megabytes(formatNumber, job.sentBytes),
                      total: megabytes(formatNumber, job.totalBytes),
                      percent: formatNumber(uploadPercent(job)),
                    })}
              </p>
            </>
          )}

          {job.phase === "done" && (
            <p className="mt-1.5 text-[11px] text-ok-ink">{t("upload.doneBody")}</p>
          )}

          {job.phase === "error" && (
            <>
              <p className="mt-1.5 text-[11px] text-danger-ink-on-soft">
                {job.detail ?? t("upload.errorBody")}
              </p>
              {job.resumable && (
                <button
                  onClick={() => retry(job.id)}
                  className="mt-2 flex items-center gap-1.5 rounded-xl bg-slate-900 px-3 py-1.5 text-[11px] font-bold text-white hover:bg-slate-800"
                >
                  <RotateCcw className="h-3 w-3" /> {t("upload.resume")}
                </button>
              )}
            </>
          )}

          {job.phase === "cancelled" && (
            <p className="mt-1.5 text-[11px] text-ink-muted">{t("upload.cancelledBody")}</p>
          )}
        </article>
      ))}
    </div>
  );
}

function Header({
  job,
  t,
  onCancel,
  onDismiss,
}: {
  job: UploadJob;
  t: ReturnType<typeof useI18n>["t"];
  onCancel: () => void;
  onDismiss: () => void;
}) {
  const running = job.phase === "uploading" || job.phase === "assembling";

  return (
    <div className="flex items-start justify-between gap-2">
      <div className="flex min-w-0 items-start gap-2">
        <span className="mt-0.5 shrink-0">
          {running && <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-600" />}
          {job.phase === "done" && <CheckCircle2 className="h-3.5 w-3.5 text-ok" />}
          {job.phase === "error" && <AlertTriangle className="h-3.5 w-3.5 text-danger-ink-on-soft" />}
          {job.phase === "cancelled" && <Upload className="h-3.5 w-3.5 text-ink-muted" />}
        </span>
        <div className="min-w-0">
          <p className="truncate text-xs font-bold text-ink">
            {running && t("upload.title", { name: job.sourceName })}
            {job.phase === "done" && t("upload.doneTitle", { name: job.sourceName })}
            {job.phase === "error" && t("upload.errorTitle", { name: job.sourceName })}
            {job.phase === "cancelled" && t("upload.cancelledTitle", { name: job.sourceName })}
          </p>
          <p className="truncate text-[11px] text-ink-muted" title={job.fileName}>
            {job.fileName}
          </p>
        </div>
      </div>

      {running ? (
        <button
          onClick={onCancel}
          aria-label={t("upload.cancel")}
          title={t("upload.cancel")}
          className="flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-full text-ink-muted hover:bg-surface-muted hover:text-danger-ink-on-soft"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      ) : (
        <button
          onClick={onDismiss}
          aria-label={t("upload.dismiss")}
          title={t("upload.dismiss")}
          className="flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-full text-ink-muted hover:bg-surface-muted hover:text-ink-secondary"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
