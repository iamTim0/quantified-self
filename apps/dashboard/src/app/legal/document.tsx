import type { Locale } from "../lib/i18n/locale";
import { translate } from "../lib/i18n/translate";
import {
  fetchLegalDocument,
  resolveLegalBody,
  type LegalSlug,
} from "../lib/legal/documents";
import LegalMarkdown from "./LegalMarkdown";

/**
 * Says which version counts.
 *
 * Rendered on the translated document only. A courtesy translation of a legal text
 * that does not say it is one invites the reader to rely on it; the German wording
 * is the one drafted against German law, and the one a dispute is decided on. On
 * the German document the same sentence would be noise.
 *
 * Takes its text as a prop rather than calling `useT()`, so that this page stays a
 * server component. It is static prose, and prose should not need JavaScript.
 */
function TranslationNotice({ text }: { text: string }) {
  return (
    <aside className="legal-notice" role="note">
      {text}
    </aside>
  );
}

/**
 * One legal page: whatever the operator wrote, or a statement that they have not
 * written it yet.
 *
 * Shared by both routes because the choice is identical for each, and because the
 * part worth getting right is not the layout but which of three notes the reader
 * gets:
 *
 * * **Nothing written** says exactly that, and nothing more. This repository used
 *   to ship a full German and English template here, and a template is the one
 *   thing a statutory notice must not be: it names a company that does not operate
 *   the service, in placeholders a reader cannot tell from real data. An empty
 *   imprint is a missing imprint, which is visible; a template imprint is a wrong
 *   one, which is not.
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
}: {
  slug: LegalSlug;
  locale: Locale;
}) {
  const written = resolveLegalBody(await fetchLegalDocument(slug), locale);

  if (!written) {
    return (
      <article>
        <h1>{translate(locale, slug === "imprint" ? "footer.imprint" : "footer.privacy")}</h1>
        <p>{translate(locale, "legal.notPublished")}</p>
      </article>
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
