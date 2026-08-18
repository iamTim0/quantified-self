"use client";

import { AlertTriangle, Home, RefreshCw, RotateCcw } from "lucide-react";
import { useT } from "../lib/i18n/provider";

/**
 * What a reader sees when a screen throws.
 *
 * Until this existed there was no error boundary anywhere in the app, so an uncaught
 * exception unmounted the tree and Next rendered its own built-in fallback: an
 * untranslated "This page couldn't load / Reload to try again, or go back", with no
 * navigation, no indication of which screen failed and no way forward other than the
 * browser's back button. That is precisely what a stale day report produced in
 * production — every sign-in ended on a blank page while every API call returned 200
 * and every server log stayed clean.
 *
 * Three things this has to do, in this order of importance:
 *
 * 1. **Not lose the rest of the app.** Mounted from `(dashboard)/error.tsx`, the
 *    layout above it survives, so the sidebar and the tab bar are still there and one
 *    broken screen costs one screen. That alone is the difference between "the
 *    analysis tab is broken" and "the dashboard is down".
 * 2. **Offer a way out that can actually work.** `reset()` re-renders the segment,
 *    which fixes a transient failure and does nothing for a bad payload; a reload
 *    refetches everything; the overview is the screen most likely to still work. All
 *    three are offered because which one helps depends on the cause, and the reader
 *    should not have to guess.
 * 3. **Be reportable.** The digest is the only handle anyone has on a minified
 *    production stack, and the message is what turns "it broke" into a search term.
 *    Both sit behind a disclosure so they inform without shouting, and the hint says
 *    outright that this names code rather than personal data — because "send us the
 *    technical detail" is a request a reader is entitled to be wary of.
 */
export default function CrashScreen({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useT();

  return (
    <section
      // `alert` rather than a plain region: this replaces content the reader was
      // already looking at, so a screen reader has to be told without being asked.
      role="alert"
      className="mx-auto w-full max-w-xl px-4 py-10"
    >
      <div className="rounded-3xl border border-danger-line bg-danger-soft p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-danger-ink-on-soft" />
          <div className="min-w-0">
            <h1 className="text-lg font-bold text-danger-ink-on-soft">{t("crash.title")}</h1>
            <p className="mt-1 text-sm leading-relaxed text-danger-ink-on-soft">
              {t("crash.detail")}
            </p>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={reset}
            className="bg-brand text-brand-ink hover:bg-brand-hover inline-flex min-h-11 items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold"
          >
            <RotateCcw className="h-4 w-4" /> {t("crash.retry")}
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm font-semibold text-ink hover:bg-surface-muted"
          >
            <RefreshCw className="h-4 w-4" /> {t("crash.reload")}
          </button>
          <a
            href="/"
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm font-semibold text-ink hover:bg-surface-muted"
          >
            <Home className="h-4 w-4" /> {t("crash.home")}
          </a>
        </div>

        <details className="mt-5">
          <summary className="cursor-pointer text-sm font-semibold text-danger-ink-on-soft">
            {t("crash.technical")}
          </summary>
          <p className="mt-2 text-xs text-danger-ink-on-soft">{t("crash.technicalHint")}</p>
          {error.digest && (
            <p className="mt-2 text-xs text-danger-ink-on-soft">
              {t("crash.digest")}: <code className="font-mono">{error.digest}</code>
            </p>
          )}
          {/* Wrapped and scrollable: a minified message is one very long line, and a
              page that scrolls sideways to show an error message is its own defect. */}
          <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-surface p-3 text-xs text-ink-secondary">
            {error.message || error.name}
          </pre>
        </details>
      </div>
    </section>
  );
}
