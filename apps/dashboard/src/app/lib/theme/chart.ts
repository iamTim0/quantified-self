"use client";

import { useEffect, useState } from "react";
import { useTheme } from "./provider";

/**
 * The theme tokens a canvas chart needs, as plain colour strings.
 *
 * Inline SVG can reference `var(--color-line)` straight from a presentation
 * attribute and needs nothing from here. A `<canvas>` cannot: Chart.js is handed
 * concrete colours in its options object, so the values have to be read out of
 * the cascade once and handed over — and read *again* when the palette changes,
 * because nothing re-runs an options object on its own.
 *
 * That gap is why every chart in this app drew light-theme scaffolding in dark
 * mode. The `[data-theme="dark"]` shim in `globals.css` rewrites Tailwind utility
 * classes; a hex literal inside a chart's options is not a class and was never
 * within its reach.
 */
export interface ChartTheme {
  /** Legend and any text that carries as much weight as body copy. */
  ink: string;
  /** Axis ticks: secondary by role, and still required to pass AA as text. */
  inkMuted: string;
  /** Grid lines and axis borders — a graphic, so 3:1 is the bar, not 4.5:1. */
  line: string;
  /** Tooltip background, which must read as raised above the card. */
  surface: string;
  /** Tooltip text. */
  surfaceInk: string;
}

/**
 * The light palette, byte-for-byte from `globals.css`.
 *
 * Used for the first paint before the effect runs. It is the light theme rather
 * than something neutral because `:root` is the light theme — a reader on the
 * light palette never sees a transition at all.
 */
const FALLBACK: ChartTheme = {
  ink: "#0f172a",
  inkMuted: "#64748b",
  line: "#e2e8f0",
  surface: "#ffffff",
  surfaceInk: "#0f172a",
};

export function useChartTheme(): ChartTheme {
  const { resolvedTheme } = useTheme();
  const [theme, setTheme] = useState<ChartTheme>(FALLBACK);

  useEffect(() => {
    const styles = getComputedStyle(document.documentElement);
    const read = (token: string, fallback: string): string =>
      styles.getPropertyValue(token).trim() || fallback;

    setTheme({
      ink: read("--foreground", FALLBACK.ink),
      inkMuted: read("--muted-foreground", FALLBACK.inkMuted),
      line: read("--border", FALLBACK.line),
      surface: read("--card", FALLBACK.surface),
      surfaceInk: read("--card-foreground", FALLBACK.surfaceInk),
    });
    // `resolvedTheme` rather than the preference: "system" resolves to either
    // palette and changes under the reader when the OS does.
  }, [resolvedTheme]);

  return theme;
}
