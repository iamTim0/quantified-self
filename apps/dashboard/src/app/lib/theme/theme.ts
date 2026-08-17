/**
 * The dashboard theme preference.
 *
 * `system` follows the operating system without copying that preference into
 * storage. The preference itself is persisted per browser, while the resolved
 * palette is kept on `<html>` so CSS can apply it before React hydrates.
 */
export const THEME_STORAGE_KEY = "qs-theme";

export const THEMES = ["system", "light", "dark"] as const;

export type Theme = (typeof THEMES)[number];

export type ResolvedTheme = Exclude<Theme, "system">;

export function isTheme(value: string | null | undefined): value is Theme {
  return value != null && (THEMES as readonly string[]).includes(value);
}

/**
 * This script runs while the document is still being parsed. Keep it small and
 * dependency-free: it is the only thing that can read localStorage early enough
 * to prevent the saved dark palette flashing light on a hard navigation.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var k="${THEME_STORAGE_KEY}",p=localStorage.getItem(k);p=p==="light"||p==="dark"||p==="system"?p:"system";var d=window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches;document.documentElement.dataset.themePreference=p;document.documentElement.dataset.theme=p==="system"?(d?"dark":"light"):p}catch(e){document.documentElement.dataset.themePreference="system";document.documentElement.dataset.theme="light"}})()`;
