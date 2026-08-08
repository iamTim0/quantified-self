/**
 * Message lookup, with no React in it.
 *
 * Separate from `provider.tsx` on purpose: that file is `"use client"`, and the root
 * layout resolves the page title on the server. A pure function should not force a
 * client boundary on whoever needs it.
 */

import { en, type MessageKey } from "./catalog-en";
import { de } from "./catalog-de";
import { DEFAULT_LOCALE, type Locale } from "./locale";

const CATALOGS: Record<Locale, Record<MessageKey, string>> = { en, de };

/** Values interpolated into `{name}` placeholders. */
export type Vars = Record<string, string | number>;

export type Translate = (key: MessageKey, vars?: Vars) => string;

/**
 * Look up one message.
 *
 * Falls back to English and then to the key itself. A visible key is ugly, and that
 * is the point: it is a bug that should be seen, not an empty element that looks
 * like missing data.
 */
export function translate(locale: Locale, key: MessageKey, vars?: Vars): string {
  const template = CATALOGS[locale]?.[key] ?? CATALOGS[DEFAULT_LOCALE][key] ?? key;
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  );
}

/**
 * Pick between two wordings by count.
 *
 * Not a plural engine: German and English both split at one, so one comparison
 * covers every case this interface has. A language with more forms would need a
 * real one, and would say so here.
 */
export function plural(count: number, one: MessageKey, other: MessageKey): MessageKey {
  return Math.abs(count) === 1 ? one : other;
}

export type { MessageKey };
