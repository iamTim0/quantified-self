"use client";

/**
 * Uploads that outlive the dialog that started them.
 *
 * An export archive takes minutes to send, and it used to be sent by the import
 * dialog itself: closing the dialog killed the request, so the dialog had to be left
 * open and watched. The upload now runs here, above every screen, and the dialog is
 * one of two things that render it — the other is the banner, which is what a
 * minimised upload looks like.
 *
 * It also sends the archive in parts, which is what makes a large one arrive at all.
 * The hops between this browser and an importer each have an opinion about how large
 * a request body may be, and the smallest wins: Cloudflare refuses a body over 100 MB
 * on every plan below Enterprise, and refuses it at the edge after roughly three
 * megabytes — so a 200 MB Apple Health export failed at "2 %" with no service in this
 * platform ever seeing it. Parts of a size the server names pass through anything.
 *
 * The server owns the offsets (see `shared_schemas/upload_spool.py`), which is what
 * makes the retries here safe: a part whose response was lost is refused with the
 * offset the server does want, so a retry continues rather than writing twice.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { apiFetch, apiUpload } from "../api";

export type UploadPhase =
  /** Parts are going out. */
  | "uploading"
  /** Everything arrived; the importer was asked to read it. */
  | "assembling"
  /** The importer accepted the archive. From here the connector's run says more. */
  | "done"
  | "error"
  | "cancelled";

export interface UploadJob {
  id: string;
  /** The connector instance this archive belongs to. */
  sourceId: string;
  sourceName: string;
  /** The provider whose importer can read the file, e.g. `apple_health`. */
  providerType: string;
  fileName: string;
  totalBytes: number;
  sentBytes: number;
  phase: UploadPhase;
  /**
   * What the service said, in its own words. Services answer in English and the
   * dashboard shows that text rather than inventing a translation for a message it
   * does not have a code for (AGENTS.md rule 17).
   */
  detail?: string;
  /** Set once the importer has accepted the archive; the run it opened. */
  syncRunId?: string | null;
  /** True while the upload can be picked up where it stopped. */
  resumable: boolean;
}

export interface StartUpload {
  apiBase: string;
  sourceId: string;
  sourceName: string;
  providerType: string;
  file: File;
}

interface UploadsValue {
  jobs: UploadJob[];
  /** The upload for one connector, if there is one — active or just finished. */
  jobFor: (sourceId: string) => UploadJob | undefined;
  start: (input: StartUpload) => void;
  /** Stops the upload and tells the importer to delete the parts it has. */
  cancel: (id: string) => void;
  /** Continues where it stopped, or starts over if the session is gone. */
  retry: (id: string) => void;
  dismiss: (id: string) => void;
}

/** What one part weighs until the server names a size of its own. */
const FALLBACK_CHUNK_BYTES = 8 * 1024 * 1024;

/** Attempts per part before the upload is called failed. */
const PART_ATTEMPTS = 4;

/** Waits between those attempts. A home connection comes back, or it does not. */
const BACKOFF_MS = [1_000, 3_000, 8_000];

/**
 * How often the server may correct our offset before we stop believing it.
 *
 * A correction is normal (a lost response, a part that half arrived) and always moves
 * the upload forward. A loop of them would not, and would send parts forever.
 */
const MAX_RESYNCS = 5;

/** How long a finished upload stays on screen before it stops being news. */
const DONE_VISIBLE_MS = 20_000;

const UploadsContext = createContext<UploadsValue | null>(null);

/** `apple_health` is the provider; `apple-health` is what the route spells. */
function uploadBase(apiBase: string, providerType: string): string {
  return `${apiBase}/api/v1/import/${providerType.replace(/_/g, "-")}/upload`;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function detailOf(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => null);
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === "string" && detail ? detail : fallback;
}

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** A part was refused for a reason no retry will change. */
class UploadRefused extends Error {}

interface Live {
  input: StartUpload;
  controller: AbortController;
  /** The server's session, once it exists. Needed to cancel or to resume. */
  uploadId?: string;
  /** Where the server said it is, which is where a resume continues from. */
  offset: number;
  /** The part size this importer asked for. The server decides, not this file. */
  chunkBytes?: number;
}

export function UploadProvider({ children }: { children: React.ReactNode }) {
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  // The File and the abort handle never render, so they live outside the state that
  // does — and a job's entry survives its failure, because that is what a resume
  // needs.
  const live = useRef(new Map<string, Live>());

  const patch = useCallback((id: string, changes: Partial<UploadJob>) => {
    setJobs((prev) => prev.map((job) => (job.id === id ? { ...job, ...changes } : job)));
  }, []);

  /**
   * Send the file, part by part, and ask the importer to read it.
   *
   * `resume` skips opening a session and continues an existing one, which is what
   * turns a failure at 80 % into 20 % of work rather than all of it again.
   */
  const run = useCallback(
    async (id: string, entry: Live, resume: boolean): Promise<void> => {
      const { apiBase, providerType, sourceId, file } = entry.input;
      const base = uploadBase(apiBase, providerType);
      const signal = entry.controller.signal;

      try {
        if (!resume || !entry.uploadId) {
          const opened = await apiFetch(
            `${base}/begin?source_id=${encodeURIComponent(sourceId)}&total_bytes=${file.size}`,
            { method: "POST", signal },
          );
          if (!opened.ok) {
            throw new UploadRefused(await detailOf(opened, "The upload could not be started."));
          }
          const session = (await opened.json()) as {
            upload_id?: string;
            chunk_bytes?: number;
            received?: number;
          };
          if (!session.upload_id) {
            throw new UploadRefused("The importer did not return an upload session.");
          }
          entry.uploadId = session.upload_id;
          entry.offset = Number(session.received) || 0;
          entry.chunkBytes = Number(session.chunk_bytes) || FALLBACK_CHUNK_BYTES;
        }

        const uploadId = entry.uploadId;
        const chunkBytes = entry.chunkBytes ?? FALLBACK_CHUNK_BYTES;
        patch(id, {
          phase: "uploading",
          sentBytes: entry.offset,
          resumable: true,
          detail: undefined,
        });

        // One update per per cent, not one per progress event. This provider sits
        // above every screen, so an unthrottled `patch` would re-render the whole
        // dashboard some thirty times a second to move a bar by a pixel.
        let shown = entry.offset;
        const step = Math.max(Math.floor(file.size / 100), 256 * 1024);
        const showProgress = (bytes: number, force = false) => {
          if (!force && bytes - shown < step) return;
          shown = bytes;
          patch(id, { sentBytes: bytes });
        };

        let resyncs = 0;
        while (entry.offset < file.size) {
          const at = entry.offset;
          const part = file.slice(at, Math.min(at + chunkBytes, file.size));

          for (let attempt = 1; ; attempt += 1) {
            let response: Response;
            try {
              response = await apiUpload(
                `${base}/chunk?upload_id=${encodeURIComponent(uploadId)}&offset=${at}`,
                part,
                {
                  headers: { "Content-Type": "application/octet-stream" },
                  onProgress: (loaded) => showProgress(at + loaded),
                  signal,
                },
              );
            } catch (error) {
              if (isAbort(error) || attempt >= PART_ATTEMPTS) throw error;
              // The part starts again from its own beginning, so the count has to
              // go back to where it started rather than keep the bytes it lost.
              showProgress(at, true);
              await pause(BACKOFF_MS[Math.min(attempt - 1, BACKOFF_MS.length - 1)]);
              continue;
            }

            if (response.status === 409) {
              // The importer holds a different offset and says which. Normal after a
              // response we never saw: resending this part would append it twice.
              const body = (await response.json().catch(() => null)) as {
                expected_offset?: number;
              } | null;
              const expected = Number(body?.expected_offset);
              if (!Number.isFinite(expected) || (resyncs += 1) > MAX_RESYNCS) {
                throw new UploadRefused(
                  "The importer and this page disagree about how much has arrived.",
                );
              }
              entry.offset = expected;
              showProgress(expected, true);
              break;
            }

            if (response.status >= 500 && attempt < PART_ATTEMPTS) {
              showProgress(at, true);
              await pause(BACKOFF_MS[Math.min(attempt - 1, BACKOFF_MS.length - 1)]);
              continue;
            }

            if (!response.ok) {
              throw new UploadRefused(await detailOf(response, "A part of the file was refused."));
            }

            const body = (await response.json().catch(() => null)) as { received?: number } | null;
            const received = Number(body?.received);
            entry.offset = Number.isFinite(received) ? received : at + part.size;
            showProgress(entry.offset, true);
            break;
          }
        }

        patch(id, { phase: "assembling", sentBytes: file.size });
        const accepted = await apiFetch(
          `${base}/complete?upload_id=${encodeURIComponent(uploadId)}`,
          { method: "POST", signal },
        );
        if (!accepted.ok) {
          throw new UploadRefused(await detailOf(accepted, "The archive could not be read."));
        }
        const result = (await accepted.json()) as { sync_run_id?: string | null };

        // The session is spent: a resume from here would have nothing to resume.
        entry.uploadId = undefined;
        patch(id, {
          phase: "done",
          sentBytes: file.size,
          syncRunId: result.sync_run_id ?? null,
          resumable: false,
        });
      } catch (error) {
        if (isAbort(error)) {
          patch(id, { phase: "cancelled", resumable: false });
          return;
        }
        const detail =
          error instanceof UploadRefused || error instanceof Error ? error.message : String(error);
        // A refusal has been decided; a network failure has not, so the parts that
        // did arrive are still worth continuing from.
        patch(id, {
          phase: "error",
          detail,
          resumable: !(error instanceof UploadRefused) && Boolean(entry.uploadId),
        });
      }
    },
    [patch],
  );

  const start = useCallback(
    (input: StartUpload) => {
      const id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `upload-${input.sourceId}-${input.file.size}-${input.file.name}`;
      const entry: Live = { input, controller: new AbortController(), offset: 0 };
      live.current.set(id, entry);

      setJobs((prev) => [
        // One upload per connector: a second file for the same one replaces the
        // first here, exactly as it does in the importer's spool.
        ...prev.filter((job) => job.sourceId !== input.sourceId),
        {
          id,
          sourceId: input.sourceId,
          sourceName: input.sourceName,
          providerType: input.providerType,
          fileName: input.file.name,
          totalBytes: input.file.size,
          sentBytes: 0,
          phase: "uploading",
          resumable: false,
        },
      ]);

      void run(id, entry, false);
    },
    [run],
  );

  const cancel = useCallback(
    (id: string) => {
      const entry = live.current.get(id);
      patch(id, { phase: "cancelled", resumable: false });
      if (!entry) return;

      entry.controller.abort();
      if (entry.uploadId) {
        const base = uploadBase(entry.input.apiBase, entry.input.providerType);
        // Told rather than left to the sweep: the parts are health data, and a
        // cancellation the user asked for should take effect now.
        void apiFetch(`${base}/abort?upload_id=${encodeURIComponent(entry.uploadId)}`, {
          method: "POST",
        }).catch(() => undefined);
        entry.uploadId = undefined;
      }
    },
    [patch],
  );

  const retry = useCallback(
    (id: string) => {
      const entry = live.current.get(id);
      if (!entry) return;
      // A fresh handle: the old one is aborted for good once it has been used.
      entry.controller = new AbortController();
      patch(id, { phase: "uploading", detail: undefined });
      void run(id, entry, Boolean(entry.uploadId));
    },
    [patch, run],
  );

  const dismiss = useCallback((id: string) => {
    live.current.delete(id);
    setJobs((prev) => prev.filter((job) => job.id !== id));
  }, []);

  // An accepted archive stops being news once the import it started is the thing
  // worth watching, and that lives on the connector.
  useEffect(() => {
    const finished = jobs.filter((job) => job.phase === "done");
    if (finished.length === 0) return;
    const timers = finished.map((job) => setTimeout(() => dismiss(job.id), DONE_VISIBLE_MS));
    return () => timers.forEach(clearTimeout);
  }, [jobs, dismiss]);

  // Closing the tab kills the upload, and nothing else would say so. The browser
  // decides the wording; all a page can do is ask to be asked.
  useEffect(() => {
    const active = jobs.some((job) => job.phase === "uploading" || job.phase === "assembling");
    if (!active) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [jobs]);

  const value = useMemo<UploadsValue>(
    () => ({
      jobs,
      jobFor: (sourceId: string) => jobs.find((job) => job.sourceId === sourceId),
      start,
      cancel,
      retry,
      dismiss,
    }),
    [jobs, start, cancel, retry, dismiss],
  );

  return <UploadsContext.Provider value={value}>{children}</UploadsContext.Provider>;
}

/**
 * The uploads in flight.
 *
 * Outside the provider this returns a value that accepts nothing and shows nothing,
 * so a component rendered in isolation (a test, a story) neither crashes nor silently
 * appears to start an upload.
 */
export function useUploads(): UploadsValue {
  const value = useContext(UploadsContext);
  return value ?? EMPTY_UPLOADS;
}

const EMPTY_UPLOADS: UploadsValue = {
  jobs: [],
  jobFor: () => undefined,
  start: () => undefined,
  cancel: () => undefined,
  retry: () => undefined,
  dismiss: () => undefined,
};

/** How far along an upload is, as a whole number of per cent. */
export function uploadPercent(job: UploadJob): number {
  if (job.totalBytes <= 0) return 0;
  return Math.min(100, Math.round((job.sentBytes / job.totalBytes) * 100));
}
