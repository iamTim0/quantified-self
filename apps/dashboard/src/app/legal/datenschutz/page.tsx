import type { Metadata } from "next";

import { requestLocale } from "../../lib/i18n/request";
import { translate } from "../../lib/i18n/translate";
import LegalDocumentPage from "../document";

/**
 * Server-rendered in both languages. The tab title, the description and the document
 * itself arrive in the reader's language on the first paint, and the page needs no
 * JavaScript at all -- which is the right property for a legal text. The language
 * switch still works because the legal layout refreshes this tree when the locale
 * changes; rendering both languages on the client instead would have shipped the
 * German and the English document to every visitor to show one of them.
 */
export async function generateMetadata(): Promise<Metadata> {
  const locale = await requestLocale();

  return {
    title: translate(locale, "legal.privacyMeta"),
    description: translate(locale, "legal.privacyMetaDescription"),
    robots: { index: false, follow: false },
  };
}

export default async function DatenschutzPage() {
  const locale = await requestLocale();
  return <LegalDocumentPage slug="privacy" locale={locale} />;
}
