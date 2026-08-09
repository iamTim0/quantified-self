import type { Metadata } from "next";

import { requestLocale } from "../../lib/i18n/request";
import Privacy from "./Privacy";

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
        title: "Datenschutzerklärung — Quantified Self",
        description:
          "Informationen zur Verarbeitung personenbezogener Daten in der Quantified-Self-Plattform.",
        robots: { index: false, follow: false },
      }
    : {
        title: "Privacy policy — Quantified Self",
        description:
          "How the Quantified Self platform processes personal data, and on what legal basis.",
        robots: { index: false, follow: false },
      };
}

export default async function DatenschutzPage() {
  return <Privacy locale={await requestLocale()} />;
}
