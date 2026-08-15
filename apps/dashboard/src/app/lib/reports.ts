"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "./api";
import { usePolling } from "./polling";

/**
 * Reading a precomputed report, and asking for a fresh one.
 *
 * The gap scan, the cross-source conflict scan and the insights bundle are
 * derivations over a workspace's whole history. They used to be recomputed on
 * every page load — the quality page additionally re-ran two of them every
 * fifteen seconds — so opening a tab cost a full scan to redraw content that was
 * identical each time. They are now computed when the data changes, and this is
 * how a page reads the result.
 *
 * `computed_at` travels with the payload on purpose: a reader shown a
 * precomputed number is entitled to know when it was true. A number with no date
 * on it is what made computing on every request feel safer than it was.
 */

/**
 * What a run may be asked for. `source_id` is a string, so typing this as
 * `Record<string, number>` forced an `as` cast at the call site that turned
 * the check off exactly where it was needed.
 */
export type ReportParams = Record<string, number | string | boolean>;

/** What a report kind is called on the wire. */
export type ReportKind = "gaps" | "conflicts" | "insights";

export interface ReportEnvelope<T> {
  kind: ReportKind;
  /** `ready` once a run has finished; `never_computed` before the first one. */
  status: "ready" | "never_computed";
  /** Newer data has arrived since this was computed. */
  stale: boolean;
  /** A run is in flight right now. */
  running: boolean;
  computed_at: string | null;
  covers_data_through: string | null;
  params: Record<string, unknown>;
  result: T | null;
}

export interface ReportState<T> extends ReportEnvelope<T> {
  /** The first load has not returned yet. Distinct from `never_computed`. */
  loading: boolean;
  /**
   * Ask Core to recompute now, optionally for different parameters.
   *
   * A window is part of a report's identity rather than a filter over it, so
   * asking for another window asks for another run.
   */
  refresh: (params?: ReportParams) => Promise<void>;
  /** Re-read the stored run without asking for a new one. */
  reload: () => Promise<void>;
}

const EMPTY: Omit<ReportEnvelope<never>, "kind"> = {
  status: "never_computed",
  stale: true,
  running: false,
  computed_at: null,
  covers_data_through: null,
  params: {},
  result: null,
};

/**
 * Read one report, and poll only while a run is actually in flight.
 *
 * The polling condition is the point: a page with nothing running makes exactly
 * one request when it opens and then goes quiet, because nothing it shows can
 * change until a run finishes.
 */
export function useReport<T>(apiBase: string, kind: ReportKind): ReportState<T> {
  const [envelope, setEnvelope] = useState<ReportEnvelope<T>>({ kind, ...EMPTY } as ReportEnvelope<T>);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    // `finally`, because every exit has to clear `loading`. A throw from
    // `response.json()` on a truncated body otherwise left the page showing a
    // spinner that nothing would ever stop.
    try {
      const response = await apiFetch(`${apiBase}/api/v1/data/reports/${kind}`);
      if (!response.ok) return;
      setEnvelope((await response.json()) as ReportEnvelope<T>);
    } catch {
      // A network blip is not news the page can act on; the next poll or the
      // next visit re-reads. What matters is that it does not get stuck.
    } finally {
      setLoading(false);
    }
  }, [apiBase, kind]);

  const refresh = useCallback(
    async (params?: ReportParams) => {
      // Optimistic: the button must feel like it did something before the first
      // poll comes back, and the server is the authority from the next tick on.
      //
      // But only optimistic — a rejected POST used to leave `running` true with
      // nothing able to clear it, so the page polled every 2.5 s forever and the
      // refresh button and both selectors stayed disabled until a reload.
      setEnvelope((current) => ({ ...current, running: true }));
      try {
        await apiFetch(`${apiBase}/api/v1/data/reports/${kind}/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(params ?? {}),
        });
      } catch {
        setEnvelope((current) => ({ ...current, running: false }));
        return;
      }
      await reload();
    },
    [apiBase, kind, reload],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) await reload();
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  usePolling(() => void reload(), envelope.running ? 2_500 : null);

  return { ...envelope, loading, refresh, reload };
}
