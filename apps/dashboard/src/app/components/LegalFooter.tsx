"use client";

import Link from "next/link";

/**
 * Footer with the legally required links.
 *
 * The application shell previously had no footer at all, so the privacy policy was
 * reachable only from the login screen and became unreachable once signed in.
 */
export default function LegalFooter({ className = "" }: { className?: string }) {
  return (
    <footer
      className={`mt-8 border-t border-slate-200 pt-4 text-xs text-slate-500 ${className}`}
    >
      <nav aria-label="Rechtliches und Dokumentation">
        <ul className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <li>
            <Link href="/legal/impressum" className="underline hover:text-slate-700">
              Impressum
            </Link>
          </li>
          <li>
            <Link href="/legal/datenschutz" className="underline hover:text-slate-700">
              Datenschutzerklärung
            </Link>
          </li>
          <li>
            <a
              href="/docs/"
              target="_blank"
              rel="noreferrer"
              className="underline hover:text-slate-700"
            >
              Dokumentation
            </a>
          </li>
        </ul>
      </nav>
    </footer>
  );
}
