"use client";

import { LOCALE_COOKIE, isLocale, localeFromAcceptLanguage, type Locale } from "./lib/i18n/locale";
import { translate } from "./lib/i18n/translate";

/**
 * The last boundary: the root layout itself failed, so nothing above this exists.
 *
 * Next replaces the whole document here, which is why this file renders its own
 * `<html>` and `<body>` — and why `LocaleProvider` is not available, since the layout
 * that mounts it is the thing that threw.
 *
 * **It is still translated, and that is deliberate.** The obvious answer was to print
 * both languages at once, as `public/offline.html` does, and to write a fifth
 * exception into AGENTS.md rule 16 for it. That would have been the wrong trade: the
 * offline page genuinely cannot reach the catalogue, because the service worker serves
 * it with no JavaScript and no styles. This file can — the catalogue is a plain object
 * in the same bundle, and the locale is in a cookie the client is allowed to read. So
 * every string here still comes from `catalog-en.ts` and `catalog-de.ts`, no rule
 * gains an exception, and a German reader gets German even on the worst page in the
 * app.
 *
 * Styling is inline for the same reason the text is resolved by hand: a failure this
 * deep may have taken the stylesheet with it, and a message nobody can read is not a
 * message. The design tokens live in `globals.css`, which the root layout imports —
 * the same root layout that just threw — so `var(--color-…)` here would resolve to
 * nothing exactly when it mattered. Hence the literals, and hence this file's entry in
 * `.agents/scripts/design_tokens_allowlist.json`: an allowance is a decision that gets
 * written down (AGENTS.md rule 14), and the reason is this paragraph.
 *
 * They are light values, deliberately. The theme bootstrap also lives in the root
 * layout, so there is no `data-theme` to honour and no persisted preference reachable
 * before paint; guessing dark would be a coin flip on a page that must be legible on
 * the first try.
 */
function clientLocale(): Locale {
  if (typeof document === "undefined") return "en";
  const cookie = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith(`${LOCALE_COOKIE}=`))
    ?.slice(LOCALE_COOKIE.length + 1);
  if (isLocale(cookie)) return cookie;
  // `navigator.language` is the client-side equivalent of `Accept-Language`, and the
  // same resolver handles the region subtag so `de-AT` still counts as German.
  return localeFromAcceptLanguage(
    typeof navigator === "undefined" ? null : navigator.language,
  );
}

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const locale = clientLocale();
  const t = (key: Parameters<typeof translate>[1]) => translate(locale, key);

  return (
    <html lang={locale}>
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "1.5rem",
          background: "#f8fafc",
          color: "#0f172a",
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        <main role="alert" style={{ maxWidth: "32rem", width: "100%" }}>
          <h1 style={{ fontSize: "1.25rem", margin: "0 0 0.5rem" }}>{t("crash.fatalTitle")}</h1>
          <p style={{ margin: "0 0 0.5rem", lineHeight: 1.6 }}>{t("crash.detail")}</p>
          <p style={{ margin: "0 0 1.25rem", lineHeight: 1.6, color: "#475569" }}>
            {t("crash.fatalDetail")}
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              minHeight: "2.75rem",
              padding: "0 1rem",
              borderRadius: "0.75rem",
              border: "none",
              background: "#0f172a",
              color: "#ffffff",
              fontSize: "0.875rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {t("crash.retry")}
          </button>
          {error.digest && (
            <p style={{ marginTop: "1.25rem", fontSize: "0.75rem", color: "#475569" }}>
              {t("crash.digest")}: <code>{error.digest}</code>
            </p>
          )}
        </main>
      </body>
    </html>
  );
}
