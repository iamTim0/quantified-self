"use client";

import Link from "next/link";

const REPOSITORY = "https://github.com/iamTim0/quantified-self";

/**
 * Where the source of *this* build lives.
 *
 * AGPL-3.0 §13: anyone interacting with the program over a network must be offered
 * the Corresponding Source of the version they are using. A link to the default
 * branch does not satisfy that — the deployed version and the branch tip drift
 * apart the moment anything is merged. The release workflow bakes the version and
 * commit in as build arguments, so this names the exact source. A build without them
 * (local development) falls back to the repository, which is where that source is.
 */
function sourceLink(): { href: string; label: string } {
  const version = process.env.NEXT_PUBLIC_SOURCE_VERSION;
  const commit = process.env.NEXT_PUBLIC_SOURCE_COMMIT;

  if (version) {
    return { href: `${REPOSITORY}/tree/v${version}`, label: `Quellcode (v${version})` };
  }
  if (commit) {
    return { href: `${REPOSITORY}/tree/${commit}`, label: `Quellcode (${commit.slice(0, 7)})` };
  }
  return { href: REPOSITORY, label: "Quellcode" };
}

/**
 * Footer with the legally required links.
 *
 * The application shell previously had no footer at all, so the privacy policy was
 * reachable only from the login screen and became unreachable once signed in.
 */
export default function LegalFooter({ className = "" }: { className?: string }) {
  const source = sourceLink();

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
          <li>
            <a
              href={source.href}
              target="_blank"
              rel="noreferrer"
              className="underline hover:text-slate-700"
            >
              {source.label}
            </a>
          </li>
        </ul>
      </nav>
    </footer>
  );
}
