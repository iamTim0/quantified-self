import type { Metadata } from "next";

import { requestLocale } from "../../lib/i18n/request";
import Imprint from "./Imprint";

/**
 * Server-rendered in both languages. The tab title, the description and the document
 * itself arrive in the reader's language on the first paint, and the page needs no
 * JavaScript at all -- which is the right property for a legal text. The language
 * switch still works because the legal layout refreshes this tree when the locale
 * changes; rendering both documents on the client instead would have shipped the
 * German and the English policy to every visitor to show one of them.
 */
export async function generateMetadata(): Promise<Metadata> {
  const locale = await requestLocale();

  return locale === "de"
    ? {
        title: "Impressum — Quantified Self",
        description: "Anbieterkennzeichnung nach § 5 DDG und § 18 Abs. 2 MStV.",
        robots: { index: false, follow: false },
      }
    : {
        title: "Legal notice — Quantified Self",
        description: "Provider identification pursuant to § 5 DDG and § 18 (2) MStV.",
        robots: { index: false, follow: false },
      };
}

export default async function ImpressumPage() {
  return <Imprint locale={await requestLocale()} />;
}
