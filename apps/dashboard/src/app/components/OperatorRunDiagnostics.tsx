"use client";

import { useI18n } from "../lib/i18n/provider";
import { durationLabel, statusKey, type SyncRun } from "./import-run";

interface OperatorRunDiagnosticsProps {
  run: SyncRun;
  userRole: string;
  typicalSeconds?: number | null;
}

function isOperator(role: string): boolean {
  return role === "owner" || role === "admin";
}

function sanitizeOperatorMessage(message: string | null, redacted: string): string {
  if (!message) return "";
  // Core bounds messages before returning them. Remove control characters once more
  // at the presentation edge so an importer cannot turn a status row into markup or
  // terminal control output. Secret-looking assignment values are redacted as a
  // defense in depth measure; this panel is never a raw log viewer or payload dump.
  const clean = message.replace(/\p{Cc}/gu, "");
  return clean
    .replace(
      /(\b(?:authorization|bearer|token|password|secret|api[_-]?key|access[_-]?token)\b\s*[:=]\s*)(["']?)[^\s,"']+/gi,
      `$1${redacted}`,
    )
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, `Bearer ${redacted}`)
    .slice(0, 512);
}

export default function OperatorRunDiagnostics({
  run,
  userRole,
  typicalSeconds = null,
}: OperatorRunDiagnosticsProps) {
  const { t, formatNumber } = useI18n();
  if (!isOperator(userRole)) return null;

  const expected = run.points_expected ?? run.points_received;
  const progress =
    expected > 0 ? Math.min(100, Math.round((run.points_processed / expected) * 100)) : null;
  const active = run.finished_at === null;
  const message = sanitizeOperatorMessage(run.message, t("importerDetail.redacted"));
  const stalled =
    active &&
    run.duration_seconds !== null &&
    run.duration_seconds >= Math.max(300, (typicalSeconds ?? 0) * 2);

  return (
    <section className="mt-3 rounded-2xl border border-line bg-surface-muted p-3 text-[11px] text-ink-secondary dark:bg-slate-800/80">
      <p className="font-bold uppercase tracking-wide text-ink-muted">
        {t("importerDetail.operatorDiagnostics")}
      </p>
      <dl className="mt-2 grid gap-x-4 gap-y-2 sm:grid-cols-2">
        <div>
          <dt className="font-semibold text-ink-muted">
            {t("importerDetail.operatorPhase")}
          </dt>
          <dd>{t(statusKey(run.status))}</dd>
        </div>
        <div>
          <dt className="font-semibold text-ink-muted">
            {t("importerDetail.operatorProgress")}
          </dt>
          <dd>
            {progress === null
              ? t("importerDetail.operatorProgressUnknown")
              : t("importerDetail.operatorProgressValue", {
                  processed: formatNumber(run.points_processed),
                  total: formatNumber(expected),
                  percent: progress,
                })}
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-ink-muted">
            {t("importerDetail.operatorElapsed")}
          </dt>
          <dd>{durationLabel(t, formatNumber, run.duration_seconds)}</dd>
        </div>
        <div>
          <dt className="font-semibold text-ink-muted">
            {t("importerDetail.requestId")}
          </dt>
          <dd className="break-all font-mono">{run.request_id}</dd>
        </div>
      </dl>
      {message && (
        <p className="mt-3 break-words border-t border-line pt-3">
          <span className="font-semibold">{t("importerDetail.operatorMessage")}: </span>
          {message}
        </p>
      )}
      {active && (
        <p className="mt-2 text-ink-muted">
          {stalled
            ? t("importerDetail.operatorStalled")
            : t("importerDetail.operatorActiveGuidance")}
        </p>
      )}
    </section>
  );
}
