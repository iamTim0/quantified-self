"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import LanguageSwitcher from "../components/LanguageSwitcher";
import { useT } from "../lib/i18n/provider";

/**
 * Layout for legal texts.
 *
 * Deliberately plain: normal headings and paragraphs, one readable column, no
 * cards, panels, icons or decorative components. A legal notice should read like a
 * document, and the styling should not distract from — or appear to qualify — the
 * text. Uses a generous measure and system-default text sizing so browser zoom and
 * reader modes behave predictably.
 *
 * A client component, unlike the pages it used to wrap: the language switcher has
 * to change this text immediately, and a server-rendered layout would keep the
 * previous language until the next full load.
 */
export default function LegalLayout({ children }: { children: ReactNode }) {
  const t = useT();

  return (
    <div className="min-h-screen bg-white text-slate-900">
      <div className="mx-auto max-w-3xl px-5 py-10 sm:px-8 sm:py-16">
        <nav
          aria-label={t("legal.nav")}
          className="mb-10 flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 pb-4"
        >
          <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <li>
              <Link href="/" className="text-slate-600 underline hover:text-slate-900">
                {t("legal.backToApp")}
              </Link>
            </li>
            <li>
              <Link
                href="/legal/datenschutz"
                className="text-slate-600 underline hover:text-slate-900"
              >
                {t("footer.privacy")}
              </Link>
            </li>
            <li>
              <Link
                href="/legal/impressum"
                className="text-slate-600 underline hover:text-slate-900"
              >
                {t("footer.imprint")}
              </Link>
            </li>
          </ul>
          <LanguageSwitcher />
        </nav>

        <main className="legal-prose">{children}</main>

        <footer className="mt-12 border-t border-slate-200 pt-4 text-sm text-slate-500">
          <p>{t("legal.disclaimer")}</p>
        </footer>
      </div>
    </div>
  );
}
