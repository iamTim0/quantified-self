import type { Locale } from "../lib/i18n/locale";
import { translate } from "../lib/i18n/translate";
import {
  fetchLegalDocument,
  resolveLegalBody,
  type LegalSlug,
} from "../lib/legal/documents";
import LegalMarkdown from "./LegalMarkdown";
import { LegalFootnote, TranslationNotice } from "./parts";

/**
 * One legal page: whatever the operator wrote, or the document this repository
 * ships when they have written nothing.
 *
 * Shared by both routes because the choice is identical for each, and because the
 * part worth getting right is not the layout but which of three notes appears above
 * and below the text:
 *
 * * **The shipped default** keeps its template disclaimer. It is full of
 *   `[placeholder]` markers and saying so is the only honest thing to do.
 * * **A written document read in German** carries no note at all. It is the binding
 *   version (rule 16) in the language it was drafted in, and a legal notice
 *   qualified by chatter it does not need reads worse for it.
 * * **A written document read in English** always says which version governs — the
 *   courtesy-translation note when an English text exists, and a different note when
 *   it does not, because German prose introduced as "a courtesy translation" tells
 *   the reader the opposite of what happened.
 */
export default async function LegalDocumentPage({
  slug,
  locale,
  fallback,
}: {
  slug: LegalSlug;
  locale: Locale;
  fallback: React.ReactNode;
}) {
  const written = resolveLegalBody(await fetchLegalDocument(slug), locale);

  if (!written) {
    return (
      <>
        {fallback}
        <LegalFootnote text={translate(locale, "legal.disclaimer")} />
      </>
    );
  }

  return (
    <article>
      {locale !== "de" && (
        <TranslationNotice
          text={translate(
            locale,
            written.translated ? "legal.translationNote" : "legal.germanOnlyNote",
          )}
        />
      )}
      <LegalMarkdown body={written.body} />
    </article>
  );
}
