"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { isTheme, THEME_STORAGE_KEY, type ResolvedTheme, type Theme } from "./theme";

interface ThemeContextValue {
  theme: Theme;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolveTheme(theme: Theme, prefersDark: boolean): ResolvedTheme {
  return theme === "system" ? (prefersDark ? "dark" : "light") : theme;
}

function readStoredTheme(): Theme {
  if (typeof window === "undefined") return "system";
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

function applyTheme(theme: Theme, prefersDark: boolean): void {
  const resolved = resolveTheme(theme, prefersDark);
  document.documentElement.dataset.themePreference = theme;
  document.documentElement.dataset.theme = resolved;
}

/**
 * Persisted theme state with a system preference that follows live OS changes.
 *
 * The initial value deliberately stays `system` during hydration. The inline
 * script in the root layout has already painted the saved palette; this avoids
 * a server/client markup mismatch in controls while the provider takes over.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("system");
  const [prefersDark, setPrefersDark] = useState(false);
  const themeRef = useRef<Theme>("system");

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const stored = readStoredTheme();
    themeRef.current = stored;
    setThemeState(stored);
    setPrefersDark(media.matches);
    applyTheme(stored, media.matches);

    const onSystemThemeChange = (event: MediaQueryListEvent) => {
      setPrefersDark(event.matches);
      if (themeRef.current === "system") applyTheme("system", event.matches);
    };
    media.addEventListener("change", onSystemThemeChange);
    return () => media.removeEventListener("change", onSystemThemeChange);
  }, []);

  const setTheme = useCallback((next: Theme) => {
    themeRef.current = next;
    setThemeState(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Private browsing and storage-disabled contexts still get the theme for
      // this session; persistence is best effort.
    }
    applyTheme(next, systemPrefersDark());
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      resolvedTheme: resolveTheme(theme, prefersDark),
      setTheme,
    }),
    [prefersDark, setTheme, theme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}
