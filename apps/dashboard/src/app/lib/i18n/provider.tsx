"use client";

/**
 * The interface language, available to every component.
 *
 * A dictionary and a context rather than a library: the whole surface is a few
 * hundred strings, the app already keeps its cross-cutting concerns in
 * `src/app/lib/` (`api.ts`, `session.ts`), and every i18n package that would fit
 * here brings message-format parsing and a build step for behaviour that
 * `String.replace` covers. What it does bring is a type error when a key is missing
 * from either catalogue — see `catalog-de.ts`.
 *
 * The initial locale arrives as a prop from the root layout, which read it from the
 * cookie on the server. That is what stops the interface from painting in one
 * language and then switching to another as the client hydrates.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { type MessageKey } from "./catalog-en";
import { translate, type Translate, type Vars } from "./translate";
import {
  INTL_LOCALE,
  LOCALE_COOKIE,
  LOCALE_COOKIE_MAX_AGE,
  type Locale,
} from "./locale";

export { translate, plural } from "./translate";
export type { MessageKey, Translate, Vars };

interface LocaleContextValue {
  locale: Locale;
  setLocale: (next: Locale) => void;
  t: Translate;
  /** The tag for `Intl`, e.g. `de-DE`. Dates and numbers follow the interface. */
  intlLocale: string;
  formatDate: (value: string | number | Date | null | undefined) => string;
  formatDateTime: (value: string | number | Date | null | undefined) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

/** What a missing date or number renders as, in either language. */
const EMPTY = "—";

export function LocaleProvider({
  initialLocale,
  children,
}: {
  initialLocale: Locale;
  children: React.ReactNode;
}) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);

  // The switcher changes the language immediately — every string is rendered on
  // the client — and the cookie is only there so the *next* request already
  // arrives in this language. `document.documentElement.lang` is kept in step
  // because screen readers and hyphenation read it, not the context.
  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    document.cookie = `${LOCALE_COOKIE}=${next};path=/;max-age=${LOCALE_COOKIE_MAX_AGE};samesite=lax`;
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo<LocaleContextValue>(() => {
    const intlLocale = INTL_LOCALE[locale];
    const dateFormat = new Intl.DateTimeFormat(intlLocale, { dateStyle: "medium" });
    const dateTimeFormat = new Intl.DateTimeFormat(intlLocale, {
      dateStyle: "medium",
      timeStyle: "short",
    });

    const parse = (input: string | number | Date | null | undefined): Date | null => {
      if (input === null || input === undefined || input === "") return null;
      const date = input instanceof Date ? input : new Date(input);
      return Number.isNaN(date.getTime()) ? null : date;
    };

    return {
      locale,
      setLocale,
      t: (key, vars) => translate(locale, key, vars),
      intlLocale,
      formatDate: (input) => {
        const date = parse(input);
        return date ? dateFormat.format(date) : EMPTY;
      },
      formatDateTime: (input) => {
        const date = parse(input);
        return date ? dateTimeFormat.format(date) : EMPTY;
      },
      formatNumber: (input, options) =>
        Number.isFinite(input) ? new Intl.NumberFormat(intlLocale, options).format(input) : EMPTY,
    };
  }, [locale, setLocale]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

function useLocaleContext(): LocaleContextValue {
  const ctx = useContext(LocaleContext);
  if (!ctx) {
    throw new Error("useT/useLocale used outside LocaleProvider — it belongs in the root layout.");
  }
  return ctx;
}

/** Everything a component needs to render text: `const { t, formatDate } = useI18n()`. */
export function useI18n(): LocaleContextValue {
  return useLocaleContext();
}

/** The common case: `const t = useT()`. */
export function useT(): Translate {
  return useLocaleContext().t;
}
