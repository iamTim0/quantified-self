"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useI18n, type MessageKey } from "../lib/i18n/provider";
import { useTheme } from "../lib/theme/provider";
import { THEMES, type Theme } from "../lib/theme/theme";

const THEME_ICON = {
  system: Monitor,
  light: Sun,
  dark: Moon,
} as const;

const THEME_LABEL: Record<Theme, MessageKey> = {
  system: "theme.system",
  light: "theme.light",
  dark: "theme.dark",
};

/** A compact three-way control: explicit light/dark, or the system preference. */
export default function ThemeSwitcher() {
  const { t } = useI18n();
  const { theme, setTheme } = useTheme();

  return (
    <div
      role="group"
      aria-label={t("theme.label")}
      className="inline-flex h-11 shrink-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
    >
      {THEMES.map((candidate) => {
        const Icon = THEME_ICON[candidate];
        const active = candidate === theme;
        const label = t(THEME_LABEL[candidate]);
        return (
          <button
            key={candidate}
            type="button"
            onClick={() => setTheme(candidate)}
            aria-pressed={active}
            aria-label={label}
            title={label}
            className={[
              "inline-flex h-full items-center justify-center gap-1 px-2.5 text-[11px] font-bold transition-colors",
              active
                ? "bg-[#0d5c3a] text-white"
                : "text-slate-500 hover:bg-slate-50 hover:text-slate-900",
            ].join(" ")}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="hidden xl:inline">{label}</span>
          </button>
        );
      })}
    </div>
  );
}
