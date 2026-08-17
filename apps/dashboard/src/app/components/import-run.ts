import type { MessageKey, Translate } from "../lib/i18n/provider";

export interface SyncRun {
  id: string;
  request_id: string | null;
  source_id: string | null;
  source_type: string;
  connector_name: string | null;
  mode: string;
  trigger: string;
  status: string;
  window_start: string | null;
  window_end: string | null;
  window_reason: string | null;
  points_expected: number | null;
  points_received: number;
  points_processed: number;
  points_accepted: number;
  points_duplicate: number;
  points_rejected: number;
  unsupported_fields: number;
  backlog_at_start: number | null;
  backlog_at_end: number | null;
  provider_window_start: string | null;
  provider_window_end: string | null;
  provider_exported_at: string | null;
  message: string | null;
  message_code: string | null;
  message_params: Record<string, string | number | boolean>;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
}

export const ACTIVE_STATUSES = new Set(["queued", "running", "loading"]);

export function statusKey(status: string): MessageKey {
  if (status === "success") return "importerDetail.statusSuccess";
  if (status === "error") return "importerDetail.statusError";
  if (status === "skipped") return "importerDetail.statusSkipped";
  if (status === "queued") return "importerDetail.statusQueued";
  if (status === "running") return "importerDetail.statusRunning";
  if (status === "loading") return "importerDetail.statusLoading";
  return "importerDetail.statusUnknown";
}

export function triggerKey(trigger: string): MessageKey {
  if (trigger === "scheduled") return "importerDetail.triggerScheduled";
  if (trigger === "manual") return "importerDetail.triggerManual";
  if (trigger === "push") return "importerDetail.triggerPush";
  if (trigger === "upload") return "importerDetail.triggerUpload";
  return "importerDetail.triggerOther";
}

export function modeKey(mode: string): MessageKey {
  if (mode === "smart") return "importerDetail.modeSmart";
  if (mode === "force") return "importerDetail.modeForce";
  return "importerDetail.modeOther";
}

export function statusClass(status: string): string {
  if (status === "success") return "border-ok-line bg-ok-soft text-ok-ink";
  if (status === "error") return "border-danger-line bg-danger-soft text-rose-800";
  if (status === "loading") return "border-info-line bg-info-soft text-sky-800";
  if (status === "skipped") return "border-line bg-surface-muted text-ink-secondary";
  return "border-warn-line bg-warn-soft text-warn-ink";
}

export function durationLabel(
  t: Translate,
  formatNumber: (value: number) => string,
  seconds: number | null,
): string {
  if (seconds === null || seconds < 0) return t("importerDetail.noDuration");
  if (seconds < 90) {
    return t("importerDetail.durationSeconds", {
      count: formatNumber(Math.max(1, Math.round(seconds))),
    });
  }
  return t("importerDetail.durationMinutes", { count: formatNumber(Math.round(seconds / 60)) });
}

/** Render only a stable server code; the server's prose is never used as UI text. */
export function messageForRun(t: Translate, run: SyncRun): string | null {
  const code = run.message_code;
  if (code === "sync_queued" || code === "sync_running") return t("importerDetail.messageQueued");
  if (code === "sync_loading") return t("importerDetail.messageLoading");
  if (code === "core_loaded") return t("importerDetail.messageCoreLoaded");
  if (code === "credentials_missing") return t("importerDetail.messageCredentialsMissing");
  if (code === "sync_skipped") return t("importerDetail.messageSkipped");
  if (code === "sync_in_flight") return t("importerDetail.messageInFlight");
  if (
    code === "sync_failed" ||
    code === "sync_plan_failed" ||
    code === "sync_queue_failed" ||
    code === "sync_not_scheduled"
  ) {
    return t("importerDetail.messageFailed");
  }
  if (code === "importer_failed") return t("importerDetail.messageImporterFailed");
  if (code === "upload_read") return t("importerDetail.messageUploadRead");
  if (code === "upload_publishing") return t("importerDetail.messageUploadPublishing");
  if (code === "upload_failed") return t("importerDetail.messageUploadFailed");
  if (code === "core_ingest_delivery_failed") {
    return t("importerDetail.messageCoreDeliveryFailed");
  }
  if (code === "invalid_json") return t("importerDetail.messageInvalidJson");
  if (code?.startsWith("payload_")) return t("importerDetail.messagePayloadInvalid");
  if (code?.startsWith("broker_")) return t("importerDetail.messageBrokerFailed");
  if (run.status === "success") return t("importerDetail.messageCoreLoaded");
  if (run.status === "error" && !run.message) return t("importerDetail.messageFailed");
  // Older runs and codes added by a newer service still have useful English
  // fallback text. Never make a status message disappear merely because the
  // dashboard has not learned a code yet.
  return run.message;
}
