"use client";

import React, { useEffect, useState, useSyncExternalStore } from "react";
import { AlertTriangle, ShieldAlert, Info, X } from "lucide-react";

import { apiFetch } from "../lib/api";
import { useT, type MessageKey, type Translate } from "../lib/i18n/provider";
import { en } from "../lib/i18n/catalog-en";

/**
 * Configuration and credential problems, shown where the operator is looking.
 *
 * All of this was already detectable — in a startup log line, in a commit
 * message, in docs/operations.md. None of which anybody reads. A platform
 * signing sessions with a key printed in its own source should say so on the
 * page, not in a file.
 *
 * Deliberately not dismissable-forever. Dismissing hides a warning for a day, per
 * code, and then it comes back until the thing is actually fixed — a permanent
 * "don't show again" on "your password is public" is how it stays public. A day is
 * the compromise: long enough that acknowledging it is worth something, short
 * enough that it cannot be silenced.
 *
 * Per code, not per banner: the point is to stop being told about the one thing
 * you have decided to live with, while a *new* problem still arrives immediately.
 *
 * The wording is translated here rather than on the server. Core sends a stable
 * `code` per warning, so the dashboard looks up `warning.<code>.*` and can speak
 * the reader's language for something the API only knows in English. A code this
 * build does not have a translation for still renders — from the server's own
 * text — because a new warning nobody has translated yet is still a warning worth
 * seeing.
 */

type Severity = "critical" | "warning" | "info";

interface SystemWarning {
  code: string;
  severity: Severity;
  title: string;
  detail: string;
  action: string;
  docs: string | null;
  /** Values for the placeholders in this warning's translation, if it has any. */
  params?: Record<string, string> | null;
}

const STYLES: Record<Severity, { box: string; icon: React.ReactNode; label: MessageKey }> = {
  critical: {
    box: "border-rose-300 bg-rose-50 text-rose-950",
    icon: <ShieldAlert className="w-5 h-5 text-rose-600 shrink-0" aria-hidden />,
    label: "warnings.severity.critical",
  },
  warning: {
    box: "border-amber-300 bg-amber-50 text-amber-950",
    icon: <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0" aria-hidden />,
    label: "warnings.severity.warning",
  },
  info: {
    box: "border-slate-300 bg-slate-50 text-slate-800",
    icon: <Info className="w-5 h-5 text-slate-500 shrink-0" aria-hidden />,
    label: "warnings.severity.info",
  },
};

const ORDER: Severity[] = ["critical", "warning", "info"];

/**
 * The command the two secret warnings tell you to run.
 *
 * It lives in the catalogue as a placeholder so the sentence around it can be
 * translated without anybody retyping a command — and so a change to the command
 * is one edit, not four.
 */
const GENERATE_SECRET = 'python -c "import secrets; print(secrets.token_urlsafe(48))"';

/** A translation for this warning's field, or the server's own wording. */
function field(
  t: Translate,
  warning: SystemWarning,
  part: "title" | "detail" | "action",
  fallback: string,
): string {
  const key = `warning.${warning.code}.${part}`;
  if (!(key in en)) return fallback;
  return t(key as MessageKey, { generate: GENERATE_SECRET, ...(warning.params ?? {}) });
}

/** Where a dismissal is remembered, and for how long. */
const DISMISSED_KEY = "qs-warnings-dismissed";
const DISMISS_FOR_MS = 24 * 60 * 60 * 1000;

/**
 * Codes dismissed less than a day ago.
 *
 * Reads defensively: this is browser storage, so the value can be absent, stale
 * from an older shape, or corrupt, and a warnings banner that throws would take the
 * page it sits on with it. Anything unreadable means "nothing is dismissed", which
 * errs towards showing a warning rather than hiding one.
 */
function readDismissed(): Map<string, number> {
  if (typeof window === "undefined") return new Map();
  try {
    const raw = window.localStorage.getItem(DISMISSED_KEY);
    if (!raw) return new Map();
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object") return new Map();
    const cutoff = Date.now() - DISMISS_FOR_MS;
    return new Map(
      Object.entries(parsed as Record<string, unknown>)
        .filter(([, at]) => typeof at === "number" && at > cutoff)
        .map(([code, at]) => [code, at as number]),
    );
  } catch {
    return new Map();
  }
}

function writeDismissed(entries: Map<string, number>): void {
  try {
    // Expired entries are dropped on write, so the key does not grow for codes
    // that stopped existing.
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    // Private mode, a full quota, storage disabled. The dismissal then lasts for
    // this view only, which is the harmless direction to fail in.
  }
}

/**
 * `localStorage` as an external store, read through `useSyncExternalStore`.
 *
 * The obvious version — read it in an effect and `setState` — is a cascading render
 * and React's own lint rule says so. Reading it in a lazy `useState` initializer
 * instead would run during render on the server, where there is no `localStorage`,
 * and make the first client render disagree with the server's HTML. This is the API
 * for exactly that shape: a value that lives outside React and has no server
 * equivalent.
 *
 * The snapshot is cached at module level because `useSyncExternalStore` compares it
 * by identity: parsing a fresh `Map` on every render would look like a new value
 * every time and never settle.
 */
const NOTHING_DISMISSED: ReadonlyMap<string, number> = new Map();

let cachedSnapshot: ReadonlyMap<string, number> | null = null;
const storeListeners = new Set<() => void>();

function invalidateDismissed(): void {
  cachedSnapshot = null;
  for (const listener of storeListeners) listener();
}

function subscribeDismissed(listener: () => void): () => void {
  storeListeners.add(listener);
  // Another tab dismissing the same warning should not be argued with.
  window.addEventListener("storage", invalidateDismissed);
  return () => {
    storeListeners.delete(listener);
    if (storeListeners.size === 0) window.removeEventListener("storage", invalidateDismissed);
  };
}

function dismissedSnapshot(): ReadonlyMap<string, number> {
  cachedSnapshot ??= readDismissed();
  return cachedSnapshot;
}

/**
 * Record a dismissal and tell every subscriber.
 *
 * At module scope rather than in the component, because it reads the clock: React's
 * lint refuses an impure call in a function it cannot prove is an event handler, and
 * it is right to — the store's mutation belongs with the store either way.
 */
function dismissCode(code: string): void {
  writeDismissed(new Map(dismissedSnapshot()).set(code, Date.now()));
  invalidateDismissed();
}

export default function SystemWarnings({ apiBase }: { apiBase: string }) {
  const t = useT();
  const [warnings, setWarnings] = useState<SystemWarning[]>([]);
  const dismissed = useSyncExternalStore(
    subscribeDismissed,
    dismissedSnapshot,
    () => NOTHING_DISMISSED,
  );

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const res = await apiFetch(`${apiBase}/api/v1/data/system/warnings`, {
          cache: "no-store",
        });
        if (!res.ok || cancelled) return;
        const data = await res.json();
        const list: SystemWarning[] = Array.isArray(data?.warnings) ? data.warnings : [];
        list.sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity));
        setWarnings(list);
      } catch {
        // A failure here must not take the dashboard with it. The warnings are
        // a diagnostic, and one that cannot load is a missing diagnostic, not a
        // broken page.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [apiBase]);

  const visible = warnings.filter((w) => !dismissed.has(w.code));
  if (visible.length === 0) return null;

  return (
    <section className="mb-6 space-y-3" aria-label={t("warnings.region")}>
      {visible.map((w) => {
        const style = STYLES[w.severity] ?? STYLES.warning;
        return (
          <div
            key={w.code}
            className={`rounded-2xl border px-4 py-3.5 ${style.box}`}
            // assertive for critical: a public signing key or a public password
            // is worth interrupting a screen reader for.
            role={w.severity === "critical" ? "alert" : "status"}
          >
            <div className="flex items-start gap-3">
              {style.icon}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] font-bold uppercase tracking-widest opacity-70">
                    {t(style.label)}
                  </span>
                  <h3 className="text-sm font-bold">{field(t, w, "title", w.title)}</h3>
                </div>
                <p className="mt-1.5 text-sm leading-relaxed opacity-90">
                  {field(t, w, "detail", w.detail)}
                </p>
                <p className="mt-2 text-sm font-semibold">
                  {/* The action is a command or a setting, not advice, so it is
                      rendered as something you can copy. */}
                  <code className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-[12px] break-all">
                    {field(t, w, "action", w.action)}
                  </code>
                </p>
                {w.docs && (
                  <a
                    href={w.docs}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-block text-xs font-semibold underline underline-offset-2 opacity-80 hover:opacity-100"
                  >
                    {t("warnings.openDocs")}
                  </a>
                )}
              </div>
              <button
                type="button"
                onClick={() => dismissCode(w.code)}
                className="shrink-0 rounded-lg p-1 opacity-50 transition hover:opacity-100"
                aria-label={t("warnings.dismiss")}
                title={t("warnings.dismissTitle")}
              >
                <X className="w-4 h-4" aria-hidden />
              </button>
            </div>
          </div>
        );
      })}
    </section>
  );
}
