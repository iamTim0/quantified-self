"use client";

import { Bell, CircleAlert, CircleCheck, Clock, Loader, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch } from "../lib/api";
import { useI18n, type MessageKey } from "../lib/i18n/provider";
import { useDialog } from "../lib/useDialog";

/** One run, exactly as `GET /api/v1/data/jobs` states it. */
type Job = {
  key: string;
  kind: "import" | "report";
  subject: string;
  status: string;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  progress: number | null;
  active: boolean;
  failed: boolean;
  message_code: string | null;
  message_params: Record<string, string | number | boolean>;
  message: string | null;
  detail: Record<string, unknown>;
};

type JobList = {
  jobs: Job[];
  active_count: number;
  unseen_count: number | null;
  failed_unseen_count: number;
  poll_recommended: boolean;
};

/**
 * Report kinds, mapped to catalogue keys.
 *
 * An import's subject is a connector type and stays verbatim — those are proper
 * names the interface already shows unchanged everywhere else. A report's is one
 * of four fixed kinds, which do need words.
 */
const REPORT_SUBJECT: Record<string, MessageKey> = {
  insights: "jobs.subject.insights",
  gaps: "jobs.subject.gaps",
  conflicts: "jobs.subject.conflicts",
  day: "jobs.subject.day",
};

/** How the reader asked for it. */
const TRIGGER_LABEL: Record<string, MessageKey> = {
  manual: "jobs.trigger.manual",
  scheduled: "jobs.trigger.scheduled",
  nightly: "jobs.trigger.nightly",
  webhook: "jobs.trigger.webhook",
  upload: "jobs.trigger.upload",
};

/** While something is running. Slow enough not to be a load, fast enough to feel live. */
const ACTIVE_POLL_MS = 4000;

/** When nothing is. The bell still has to notice a scheduled run starting on its own. */
const IDLE_POLL_MS = 60_000;

/**
 * Where "last looked" is kept.
 *
 * The browser, not the database: whether *this reader* has seen a notification is
 * not a property of the workspace, and storing it server-side would mean two people
 * sharing a workspace clear each other's badges.
 */
const SEEN_KEY = "qs-jobs-seen-at";

function readSeenAt(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(SEEN_KEY);
  } catch {
    // Private mode, or storage disabled. The bell then simply never claims
    // anything is new, which is the safe direction to fail in.
    return null;
  }
}

function writeSeenAt(value: string): void {
  try {
    window.localStorage.setItem(SEEN_KEY, value);
  } catch {
    /* see readSeenAt */
  }
}

function StatusIcon({ job }: { job: Job }) {
  if (job.active) {
    return <Loader className="text-brand-strong h-4 w-4 animate-spin" aria-hidden="true" />;
  }
  if (job.failed) {
    return <CircleAlert className="text-danger h-4 w-4" aria-hidden="true" />;
  }
  return <CircleCheck className="text-brand-strong h-4 w-4" aria-hidden="true" />;
}

/**
 * Everything the workspace has running, and what finished while nobody looked.
 *
 * A nightly analysis that failed at 03:00 used to be visible nowhere until somebody
 * opened the analysis tab and read a sentence about a run timeout. Imports had their
 * own page, reports had a line above the chart they fed, and neither told the reader
 * anything unless the reader already suspected something.
 */
export default function NotificationBell({ apiBase }: { apiBase: string }) {
  const { t, formatDateTime, formatNumber } = useI18n();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<JobList | null>(null);
  const [failed, setFailed] = useState(false);
  const [seenAt, setSeenAt] = useState<string | null>(null);
  const panelRef = useDialog<HTMLDivElement>(open, () => setOpen(false));
  // Read in an effect rather than in `useState`'s initialiser: `localStorage` does
  // not exist while the server renders this, and reading it during the first client
  // render would make that render disagree with the server's.
  useEffect(() => setSeenAt(readSeenAt()), []);

  const load = useCallback(async () => {
    const query = new URLSearchParams({ limit: "30" });
    // `URLSearchParams` and not string concatenation: the value is an ISO timestamp
    // whose `+00:00` offset has to be escaped, or it arrives as a space and the
    // request is a 422.
    if (seenAt) query.set("since", seenAt);
    try {
      const response = await apiFetch(`${apiBase}/api/v1/data/jobs?${query}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        setFailed(true);
        return;
      }
      setData((await response.json()) as JobList);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [apiBase, seenAt]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      if (cancelled) return;
      await load();
      if (cancelled) return;
      // The server says whether anything is in flight, so the two ends cannot
      // disagree about what "still running" means.
      timer = setTimeout(tick, data?.poll_recommended ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // `data?.poll_recommended` deliberately: the cadence has to change when work
    // starts or stops, and this is the value that says so.
  }, [load, data?.poll_recommended]);

  const badge = useMemo(() => {
    if (!data) return 0;
    // While something is running the bell counts that instead, so opening the panel
    // does not clear a badge for work that has not finished.
    return data.active_count > 0 ? data.active_count : (data.unseen_count ?? 0);
  }, [data]);

  const togglePanel = () => {
    const next = !open;
    setOpen(next);
    if (next) {
      // Marked seen on open, not on close: the reader has now looked. Anything that
      // finishes while the panel is open counts as new on the following poll, which
      // is the honest reading of "since I last looked".
      const now = new Date().toISOString();
      writeSeenAt(now);
      setSeenAt(now);
    }
  };

  const subjectOf = (job: Job) => {
    if (job.kind === "report") {
      const key = REPORT_SUBJECT[job.subject];
      return key ? t(key) : job.subject;
    }
    const name = job.detail.source_name;
    return typeof name === "string" && name ? name : job.subject;
  };

  const detailOf = (job: Job) => {
    if (job.message_code) {
      // The server's own English sentence is the fallback for a code this build does
      // not know, exactly as `ReportStatus` does it (rule 17).
      const key = `jobs.code.${job.message_code}` as MessageKey;
      const known = key in MESSAGE_CODES;
      if (known) return t(key, job.message_params as Record<string, string | number>);
      return job.message ?? job.message_code;
    }
    if (job.kind === "import" && typeof job.detail.points_accepted === "number") {
      return t("jobs.pointsStored", { count: formatNumber(job.detail.points_accepted as number) });
    }
    if (job.kind === "report" && typeof job.detail.days === "number") {
      return t("jobs.overDays", { days: formatNumber(job.detail.days as number) });
    }
    return "";
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={togglePanel}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={
          badge > 0 ? t("jobs.bellWithCount", { count: String(badge) }) : t("jobs.bell")
        }
        title={t("jobs.bell")}
        className="border-line bg-surface text-ink-muted hover:text-ink relative flex h-11 w-11 items-center justify-center rounded-2xl border shadow-sm [transition-property:color,background-color,border-color,box-shadow] hover:bg-slate-50"
      >
        <Bell className="h-4 w-4" aria-hidden="true" />
        {badge > 0 && (
          <span
            className={`absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-[10px] font-bold ${
              data && data.failed_unseen_count > 0
                ? "bg-danger text-white"
                : "bg-brand text-brand-ink"
            }`}
          >
            {badge > 9 ? "9+" : badge}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-label={t("jobs.title")}
          tabIndex={-1}
          // Right-anchored under the bell on a wide screen; a full-width sheet on a
          // phone, where a 22rem popover anchored to the right edge would hang off it.
          className="border-line bg-surface fixed inset-x-2 top-20 z-50 max-h-[70vh] overflow-y-auto overscroll-contain rounded-2xl border shadow-2xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-13 sm:w-[24rem]"
        >
          <div className="border-line flex items-center justify-between gap-3 border-b px-4 py-3">
            <h2 className="text-ink text-sm font-bold">{t("jobs.title")}</h2>
            <button
              type="button"
              onClick={() => void load()}
              aria-label={t("jobs.refresh")}
              title={t("jobs.refresh")}
              className="text-ink-muted hover:text-ink flex h-8 w-8 items-center justify-center rounded-lg"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>

          {failed ? (
            <p className="text-ink-muted px-4 py-6 text-center text-xs">{t("jobs.loadFailed")}</p>
          ) : !data || data.jobs.length === 0 ? (
            <p className="text-ink-muted px-4 py-6 text-center text-xs">{t("jobs.empty")}</p>
          ) : (
            <ul className="divide-line divide-y">
              {data.jobs.map((job) => (
                <li key={job.key} className="flex gap-3 px-4 py-3">
                  <span className="mt-0.5 shrink-0">
                    <StatusIcon job={job} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="text-ink truncate text-sm font-semibold">
                        {subjectOf(job)}
                      </span>
                      <span className="text-ink-muted shrink-0 text-[11px]">
                        {t(TRIGGER_LABEL[job.trigger] ?? "jobs.trigger.scheduled")}
                      </span>
                    </span>
                    <span className="text-ink-muted mt-0.5 block text-xs">{detailOf(job)}</span>
                    {job.active && job.progress !== null && (
                      <span
                        className="bg-surface-muted mt-1.5 block h-1 overflow-hidden rounded-full"
                        role="progressbar"
                        aria-valuenow={Math.round(job.progress * 100)}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      >
                        <span
                          className="bg-brand block h-full rounded-full"
                          style={{ width: `${Math.round(job.progress * 100)}%` }}
                        />
                      </span>
                    )}
                    {job.active && job.progress === null && (
                      // No bar rather than a made-up one: a push import and a
                      // derivation both have no denominator, and a bar that sits at
                      // one value for the whole run reads as a stuck job.
                      <span className="text-ink-muted mt-1 flex items-center gap-1 text-[11px]">
                        <Clock className="h-3 w-3" aria-hidden="true" />
                        {t("jobs.running")}
                      </span>
                    )}
                    <span className="text-ink-muted mt-0.5 block text-[11px]">
                      {formatDateTime(job.finished_at ?? job.started_at)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Message codes this build knows how to say in the reader's language.
 *
 * A set rather than a map, because the key is derived from the code — the check is
 * only "do we have words for this", and anything else falls back to the server's own
 * English sentence rather than rendering a raw identifier.
 */
const MESSAGE_CODES: Record<string, true> = {
  "jobs.code.report_timeout": true,
  "jobs.code.report_never_claimed": true,
};
