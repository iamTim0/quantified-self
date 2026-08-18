import { Fragment, type ReactNode } from "react";

/**
 * Marks a value the operator must supply before going live.
 *
 * Translated along with the surrounding text: a placeholder is an instruction to
 * whoever deploys this, and an instruction in a language they are not reading is
 * not one. The consequence is that filling in one language does not fill in the
 * other — both documents have to be completed, which is what the highlight is for.
 */
export function Placeholder({ children }: { children: ReactNode }) {
  return <span className="placeholder">[{children}]</span>;
}

/**
 * Says which version counts.
 *
 * Rendered on the translated document only. A courtesy translation of a legal text
 * that does not say it is one invites the reader to rely on it; the German wording
 * is the one drafted against German law, and the one a dispute is decided on. On
 * the German document the same sentence would be noise.
 *
 * Takes its text as a prop rather than calling `useT()`, so that the documents stay
 * server components. They are static prose, and prose should not need JavaScript.
 */
export function TranslationNotice({ text }: { text: string }) {
  return (
    <aside className="legal-notice" role="note">
      {text}
    </aside>
  );
}

/**
 * Renders the sections of a legal document in a fixed order.
 *
 * The order lives in one `as const` array per document and both languages are typed
 * `Record<SectionId, ReactNode>` against it. That is the same mechanism the message
 * catalogues use, and it is here for the same reason: a section added to the German
 * privacy policy and forgotten in the English one is a type error rather than an
 * English reader being told about three cookies while four are set. Rule 16 of
 * AGENTS.md promises the two halves change together; this is what makes the promise
 * checkable instead of aspirational.
 */
export function Sections<Id extends string>({
  order,
  sections,
}: {
  order: readonly Id[];
  sections: Record<Id, ReactNode>;
}) {
  return (
    <>
      {order.map((id) => (
        <Fragment key={id}>{sections[id]}</Fragment>
      ))}
    </>
  );
}

/**
 * The note under a document, stating what kind of text the reader just read.
 *
 * It belongs to the page rather than to the legal layout, and that move is the
 * whole point of the component. The layout printed "these texts are a template and
 * are no substitute for legal advice" under every legal page unconditionally —
 * true of the shipped default, and false and faintly alarming under an imprint the
 * operator wrote themselves and had reviewed. Only the page knows which of the two
 * it just rendered.
 */
export function LegalFootnote({ text }: { text: string }) {
  return (
    <footer className="mt-12 border-t border-line pt-4 text-sm text-ink-muted">
      <p>{text}</p>
    </footer>
  );
}
