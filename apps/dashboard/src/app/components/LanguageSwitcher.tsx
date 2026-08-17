"use client";

import { LOCALES, LOCALE_LABELS, LOCALE_SHORT } from "../lib/i18n/locale";
import { useI18n } from "../lib/i18n/provider";

/**
 * Two buttons, not a dropdown.
 *
 * With exactly two languages a select box costs a click to see what the options
 * even are, and hides which one is active behind a collapsed control. A segmented
 * pair shows both states at once and switches in one press. `aria-pressed` carries
 * the active state for screen readers, so the highlight is not the only signal.
 */
export default function LanguageSwitcher({ className = "" }: { className?: string }) {
  const { locale, setLocale, t } = useI18n();

  return (
    <div
      role="group"
      aria-label={t("lang.label")}
      className={`inline-flex h-11 shrink-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm ${className}`}
    >
      {LOCALES.map((candidate) => {
        const active = candidate === locale;
        return (
          <button
            key={candidate}
            type="button"
            onClick={() => setLocale(candidate)}
            aria-pressed={active}
            title={t("lang.switchTo", { language: LOCALE_LABELS[candidate] })}
            className={`h-full px-2.5 text-[11px] font-bold tracking-wider transition-colors ${
              active
                ? "bg-[#0d5c3a] text-white"
                : "text-slate-500 hover:bg-slate-50 hover:text-slate-900"
            }`}
          >
            {LOCALE_SHORT[candidate]}
          </button>
        );
      })}
    </div>
  );
}
