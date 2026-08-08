"use client";

import React, { useEffect, useState } from "react";
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
 * Deliberately not dismissable-forever. `critical` entries come back on every
 * load until the thing is actually fixed, because a permanent "don't show again"
 * on "your password is public" is how it stays public. Dismissing hides it for
 * this session only.
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

export default function SystemWarnings({ apiBase }: { apiBase: string }) {
  const t = useT();
  const [warnings, setWarnings] = useState<SystemWarning[]>([]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

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

  const visible = warnings.filter((w) => !hidden.has(w.code));
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
                onClick={() => setHidden((prev) => new Set(prev).add(w.code))}
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
