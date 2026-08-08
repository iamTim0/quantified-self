/**
 * Which language the interface speaks, and how that is decided.
 *
 * Deliberately not Next's recommended `[lang]` route segment. That approach exists
 * for public pages a search engine indexes per language; this dashboard is behind a
 * login, has no public surface, and moving every route under `/[lang]/` would
 * rewrite every path, redirect and bookmark for an app whose only reader is its
 * owner. The locale is a preference, so it lives where preferences live: in a
 * cookie, readable by the server so the first paint is already in the right
 * language.
 *
 * This module holds no React and no "use client" — the root layout imports it on
 * the server to pick the locale, the provider imports it on the client to render.
 */

export const LOCALES = ["en", "de"] as const;

export type Locale = (typeof LOCALES)[number];

/**
 * English, because the repository is English: the code, the comments, the
 * documentation and every message the services emit. A German browser still gets
 * German — see `resolveLocale` — but a request that states no preference gets the
 * language the project is written in.
 */
export const DEFAULT_LOCALE: Locale = "en";

/** Set by the switcher, read by the layout. Not httpOnly: the client writes it. */
export const LOCALE_COOKIE = "qs-locale";

/** A year. The choice is a preference, not a session. */
export const LOCALE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

export function isLocale(value: string | null | undefined): value is Locale {
  return value != null && (LOCALES as readonly string[]).includes(value);
}

/**
 * Pick a locale from the strongest available evidence.
 *
 * An explicit choice always wins; without one, the browser's `Accept-Language`
 * decides. Region subtags are matched loosely (`de-AT` counts as German) and the
 * q-values are honoured, so a browser that prefers Dutch and then German lands on
 * German rather than on whichever supported tag appears first in the header.
 */
export function resolveLocale(
  cookieValue: string | null | undefined,
  acceptLanguage: string | null | undefined,
): Locale {
  if (isLocale(cookieValue)) return cookieValue;
  return localeFromAcceptLanguage(acceptLanguage);
}

export function localeFromAcceptLanguage(header: string | null | undefined): Locale {
  if (!header) return DEFAULT_LOCALE;

  const ranked = header
    .split(",")
    .map((part) => {
      const [tag, ...params] = part.trim().split(";");
      const q = params
        .map((p) => p.trim())
        .find((p) => p.startsWith("q="))
        ?.slice(2);
      const quality = q === undefined ? 1 : Number.parseFloat(q);
      return { tag: tag.trim().toLowerCase(), quality: Number.isNaN(quality) ? 0 : quality };
    })
    .filter((entry) => entry.tag !== "" && entry.quality > 0)
    .sort((a, b) => b.quality - a.quality);

  for (const { tag } of ranked) {
    if (tag === "*") return DEFAULT_LOCALE;
    const base = tag.split("-")[0];
    if (isLocale(base)) return base;
  }
  return DEFAULT_LOCALE;
}

/** What the switcher shows. Each language names itself, as it should. */
export const LOCALE_LABELS: Record<Locale, string> = {
  en: "English",
  de: "Deutsch",
};

/** Short form for the switcher's compact state. */
export const LOCALE_SHORT: Record<Locale, string> = {
  en: "EN",
  de: "DE",
};

/**
 * The tag handed to `Intl` and to `<html lang>`.
 *
 * `de-DE` rather than `de`, so dates and numbers format the way a German reader
 * expects rather than the way a bare language tag leaves to the implementation.
 */
export const INTL_LOCALE: Record<Locale, string> = {
  en: "en-GB",
  de: "de-DE",
};
