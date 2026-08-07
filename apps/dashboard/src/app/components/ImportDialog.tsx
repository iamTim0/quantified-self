"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CalendarRange,
  CheckCircle2,
  History,
  Loader2,
  RefreshCw,
  ShieldCheck,
  SkipForward,
  X,
  Zap,
} from "lucide-react";

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

export interface SyncRun {
  id: string;
  request_id: string;
  mode: string;
  trigger: string;
  status: string;
  window_start: string | null;
  window_end: string | null;
  window_reason: string | null;
  points_received: number;
  points_accepted: number;
  points_duplicate: number;
  message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

interface ImportDialogProps {
  apiBase: string;
  token: string;
  sourceType: string;
  sourceName: string;
  isOpen: boolean;
  onClose: () => void;
  onQueued?: () => void;
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

function formatRange(range: ImportRange): string {
  const fmt = new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${fmt.format(new Date(range.start))} – ${fmt.format(new Date(range.end))}`;
}

function durationLabel(range: ImportRange): string {
  const ms = new Date(range.end).getTime() - new Date(range.start).getTime();
  const hours = ms / 3_600_000;
  if (hours < 48) return `${Math.max(1, Math.round(hours))} Std.`;
  return `${Math.round(hours / 24)} Tage`;
}

export default function ImportDialog({
  apiBase,
  token,
  sourceType,
  sourceName,
  isOpen,
  onClose,
  onQueued,
}: ImportDialogProps) {
  const [mode, setMode] = useState<"smart" | "force">("smart");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [planning, setPlanning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState("");
  // Suppresses the "suggested range" hint once the user edits the pickers.
  const [rangeTouched, setRangeTouched] = useState(false);

  const authHeaders = useCallback(
    () => ({ "Content-Type": "application/json", Authorization: `Bearer ${token}` }),
    [token],
  );

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
        const res = await fetch(
          `${apiBase}/api/v1/data/sources/${sourceType}/import-plan`,
          { method: "POST", headers: authHeaders(), body: JSON.stringify(body) },
        );
        if (!res.ok) {
          const detail = await res.json().catch(() => null);
          throw new Error(detail?.detail || "Importplan konnte nicht geladen werden.");
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
      const res = await fetch(
        `${apiBase}/api/v1/data/sources/${sourceType}/sync-runs?limit=5`,
        { headers: authHeaders() },
      );
      if (res.ok) setRuns((await res.json()).runs || []);
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

  const handleImport = async () => {
    setSubmitting(true);
    setError("");
    setResult("");
    try {
      const res = await fetch(`${apiBase}/api/v1/data/sources/sync`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          source_type: sourceType,
          mode,
          start: start ? fromLocalInput(start) : undefined,
          end: end ? fromLocalInput(end) : undefined,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || "Import konnte nicht gestartet werden.");

      setResult(
        data?.status === "skipped"
          ? "Nichts zu tun — der Zeitraum ist bereits vollständig vorhanden."
          : "Import wurde eingereiht.",
      );
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
                Daten importieren — {sourceName}
              </h2>
              <p className="text-[11px] text-slate-500">
                Zeitraum prüfen und anpassen, bevor der Import startet.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Dialog schließen"
            className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-5 px-6 py-5">
          {/* Range */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-slate-500">
                Von
              </span>
              <input
                type="datetime-local"
                value={start}
                onChange={(e) => {
                  setStart(e.target.value);
                  setRangeTouched(true);
                }}
                className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 outline-none focus:border-[#0d5c3a]"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-slate-500">
                Bis
              </span>
              <input
                type="datetime-local"
                value={end}
                onChange={(e) => {
                  setEnd(e.target.value);
                  setRangeTouched(true);
                }}
                className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 outline-none focus:border-[#0d5c3a]"
              />
            </label>
          </div>

          {plan?.window_reason && !rangeTouched && (
            <p className="text-[11px] leading-relaxed text-slate-500">
              <span className="font-semibold text-slate-600">Vorschlag:</span>{" "}
              {plan.window_reason}
            </p>
          )}

          {/* Mode */}
          <fieldset className="space-y-2">
            <legend className="mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">
              Modus
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
                  <ShieldCheck className="h-4 w-4 text-[#0d5c3a]" /> Smart (empfohlen)
                </span>
                <span className="mt-0.5 block text-[11px] leading-relaxed text-slate-600">
                  Bereits vollständig vorhandene Zeiträume werden übersprungen. Nur der
                  fehlende Bereich wird importiert.
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
                  <Zap className="h-4 w-4 text-amber-600" /> Alles erzwingen
                </span>
                <span className="mt-0.5 block text-[11px] leading-relaxed text-slate-600">
                  Der gesamte Zeitraum wird erneut verarbeitet.
                </span>
              </span>
            </label>
          </fieldset>

          {mode === "force" && (
            <div className="flex gap-2.5 rounded-2xl border border-amber-200 bg-amber-50 p-3.5">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <p className="text-[11px] leading-relaxed text-amber-900">
                Force-Importe verursachen deutlich mehr Verarbeitungsaufwand und erzeugen
                Duplicate Events. Doppelte Datenpunkte entstehen dank Idempotenz nicht,
                aber der Lauf dauert länger und belastet das API-Kontingent des Anbieters.
                Der Lauf wird im Importprotokoll als <code>force</code> gekennzeichnet.
              </p>
            </div>
          )}

          {/* Plan preview */}
          <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                Vorschau
              </h3>
              {planning && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />}
            </div>

            {!plan && !planning && (
              <p className="text-xs text-slate-500">Noch keine Analyse verfügbar.</p>
            )}

            {plan && (
              <div className="space-y-2.5">
                <p className="text-xs leading-relaxed text-slate-700">{plan.reason}</p>

                {plan.confidence === "low" && (
                  <p className="rounded-xl bg-slate-100 px-3 py-2 text-[11px] text-slate-600">
                    Die vorhandenen Daten sind zu unregelmäßig für eine sichere
                    Bereichserkennung. Sicherheitshalber wird der volle Zeitraum importiert.
                  </p>
                )}

                {plan.skipped_ranges.length > 0 && (
                  <div>
                    <p className="mb-1 flex items-center gap-1.5 text-[11px] font-bold text-slate-600">
                      <SkipForward className="h-3.5 w-3.5" /> Wird übersprungen
                    </p>
                    <ul className="space-y-1">
                      {plan.skipped_ranges.map((r) => (
                        <li
                          key={`${r.start}-${r.end}`}
                          className="flex items-center justify-between rounded-lg bg-white px-2.5 py-1.5 text-[11px] text-slate-600"
                        >
                          <span className="font-mono">{formatRange(r)}</span>
                          <span className="text-slate-400">{durationLabel(r)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {effective ? (
                  <div>
                    <p className="mb-1 flex items-center gap-1.5 text-[11px] font-bold text-[#0d5c3a]">
                      <RefreshCw className="h-3.5 w-3.5" /> Wird importiert
                    </p>
                    <div className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[11px] text-emerald-900">
                      <span className="font-mono">{formatRange(effective)}</span>
                      <span>{durationLabel(effective)}</span>
                    </div>
                  </div>
                ) : (
                  <p className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-700">
                    <CheckCircle2 className="h-3.5 w-3.5" /> Nichts zu importieren.
                  </p>
                )}

                {plan.docs_url && (
                  <a
                    href={plan.docs_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-block text-[11px] text-[#0d5c3a] underline"
                  >
                    Wie Smart- und Force-Import funktionieren
                  </a>
                )}
              </div>
            )}
          </div>

          {/* History */}
          {runs.length > 0 && (
            <details className="rounded-2xl border border-slate-200 bg-white p-4">
              <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">
                <History className="h-3.5 w-3.5" /> Letzte Importe ({runs.length})
              </summary>
              <ul className="mt-3 space-y-2">
                {runs.map((run) => (
                  <li key={run.id} className="rounded-xl bg-slate-50 px-3 py-2 text-[11px]">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-700">
                        {run.started_at
                          ? new Date(run.started_at).toLocaleString("de-DE")
                          : "—"}
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
                      {run.points_accepted} neu · {run.points_duplicate} Duplikate
                    </p>
                    {run.message && (
                      <p className="mt-0.5 text-slate-400">{run.message}</p>
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
            Abbrechen
          </button>
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
            {nothingToDo && mode === "smart" ? "Nichts zu importieren" : "Import starten"}
          </button>
        </div>
      </div>
    </div>
  );
}
