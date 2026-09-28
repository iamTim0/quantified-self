"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";

import LanguageSwitcher from "../components/LanguageSwitcher";
import { useI18n } from "../lib/i18n/provider";

/**
 * Layout for legal texts.
 *
 * Deliberately plain: normal headings and paragraphs, one readable column, no
 * cards, panels, icons or decorative components. A legal notice should read like a
 * document, and the styling should not distract from — or appear to qualify — the
 * text. Uses a generous measure and system-default text sizing so browser zoom and
 * reader modes behave predictably.
 *
 * A client component, unlike the documents it wraps: it carries the language
 * switcher, and it is what makes the switch take effect on a server-rendered page.
 */
export default function LegalLayout({ children }: { children: ReactNode }) {
  const { locale, t } = useI18n();
  const router = useRouter();
  const rendered = useRef(locale);

  // The documents are server components, so switching the language has to re-fetch
  // this route rather than re-render in place. `setLocale` has already written the
  // `qs-locale` cookie synchronously, so the refresh renders in the new language.
  // Guarded on the locale actually having changed: without the ref this would fire
  // a needless refresh on every mount.
  useEffect(() => {
    if (rendered.current === locale) return;
    rendered.current = locale;
    router.refresh();
  }, [locale, router]);

  return (
    <div className="min-h-dvh bg-surface pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] pt-[env(safe-area-inset-top)] text-ink">
      <a
        href="#legal-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-100 focus:rounded-xl focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:font-bold focus:text-ink focus:shadow-lg focus:outline-2 focus:outline-brand"
      >
        {t("nav.skipToContent")}
      </a>
      <div className="mx-auto max-w-3xl px-5 py-10 sm:px-8 sm:py-16">
        <nav
          aria-label={t("legal.nav")}
          className="mb-10 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4"
        >
          <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <li>
              <Link href="/" className="text-ink-muted underline hover:text-ink">
                {t("legal.backToApp")}
              </Link>
            </li>
            <li>
              <Link
                href="/legal/datenschutz"
                className="text-ink-muted underline hover:text-ink"
              >
                {t("footer.privacy")}
              </Link>
            </li>
            <li>
              <Link
                href="/legal/impressum"
                className="text-ink-muted underline hover:text-ink"
              >
                {t("footer.imprint")}
              </Link>
            </li>
          </ul>
          <LanguageSwitcher />
        </nav>

        <main id="legal-content" className="legal-prose" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
