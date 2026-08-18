import type { Locale } from "../i18n/locale";

/**
 * Reading the imprint and the privacy policy an operator has written.
 *
 * Both documents ship with a full German and English default, and for a long time
 * that default was all a deployment could show: the text lived in two TSX
 * components carrying `[placeholder]` markers, so naming the company meant editing
 * source and rebuilding an image. Anyone who does not do that ran a public service
 * whose legal notice identified nobody.
 *
 * Fetched on the server, in the page that renders it. These are the two routes in
 * the product that need no session and — before this — no JavaScript, and both
 * properties are worth keeping: a legal text should be in the first response, in
 * the reader's language, without waiting on a client fetch that can fail.
 *
 * Server-only by construction rather than by an `import "server-only"` guard: that
 * package is not a dependency here, and adding one to state a fact is worse than
 * stating it. `fetchLegalDocument` reads `process.env.INTERNAL_API_URL`, which is
 * `undefined` in a browser bundle, so a client import would silently call loopback
 * from the reader's own machine. Import this from server components only.
 */
export const LEGAL_SLUGS = ["imprint", "privacy"] as const;

export type LegalSlug = (typeof LEGAL_SLUGS)[number];

export interface LegalDocument {
  slug: LegalSlug;
  body_de: string | null;
  body_en: string | null;
  /** `custom` once any language has been written; `default` while neither has. */
  source: "custom" | "default";
  updated_at: string | null;
}

/**
 * Where this server process reaches the API.
 *
 * The browser calls its own origin, which Traefik routes to the Gateway. A server
 * component has no origin to call, so it needs an address of its own — and by
 * rule 18 the default is loopback and the port the Gateway actually binds, never a
 * container name. `api-gateway:8000` is set in the two compose files, where it is
 * true; here it would be a hostname that resolves nowhere on a developer's machine
 * and costs a DNS failure plus a connect timeout on a page that must not hang.
 */
export const DEFAULT_INTERNAL_API_URL = "http://127.0.0.1:8000";

function internalApiBase(): string {
  return (process.env.INTERNAL_API_URL || DEFAULT_INTERNAL_API_URL).replace(/\/+$/, "");
}

/**
 * The stored document, or null when there is none — and equally when it cannot be
 * fetched.
 *
 * The two are collapsed deliberately. A legal page whose API is unreachable must
 * still render: the caller answers null by showing the shipped default, which is a
 * complete document that says on its face that it is a template. The alternative —
 * an error page where a statutory notice belongs — fails in the one way that is
 * worse than showing a template, and it fails at exactly the moment the platform
 * is already having a bad day.
 *
 * A short timeout for the same reason. This request sits in front of the first
 * byte of a public page, so it is better to render the default a second early than
 * to hold the response open waiting for a service that is not coming back.
 */
export async function fetchLegalDocument(slug: LegalSlug): Promise<LegalDocument | null> {
  try {
    const response = await fetch(`${internalApiBase()}/api/v1/legal/documents/${slug}`, {
      // Never cached. An operator who corrects an address in the privacy policy
      // expects the correction to be live, and a legal document is read rarely
      // enough that there is nothing here worth caching.
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    const body = (await response.json()) as LegalDocument;
    return body.source === "custom" ? body : null;
  } catch {
    return null;
  }
}

/**
 * Which text a reader of `locale` gets, and whether it is in their language.
 *
 * The fallback is the decision worth stating. A document written only in German is
 * shown to English readers as well, rather than falling back to the shipped English
 * template — because the two documents would then describe different processing,
 * and each reader would believe theirs was the accurate one. Rule 16 makes exactly
 * that argument for the halves of a legal text, and a current document in the wrong
 * language is the lesser failure: `translated` is false, so the page keeps the note
 * saying which version governs.
 *
 * German never falls back to English. It is the binding half (rule 16), so there is
 * no case where showing the courtesy translation in its place is correct.
 */
export function resolveLegalBody(
  document: LegalDocument | null,
  locale: Locale,
): { body: string; translated: boolean } | null {
  if (!document) return null;
  const de = document.body_de?.trim() || "";
  const en = document.body_en?.trim() || "";

  if (locale === "de") return de ? { body: de, translated: true } : null;
  if (en) return { body: en, translated: true };
  return de ? { body: de, translated: false } : null;
}
