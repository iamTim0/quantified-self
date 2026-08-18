"use client";

import { useCallback, useEffect, useState } from "react";
import { Eye, FileText, Pencil, ShieldCheck } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { apiFetch } from "../lib/api";
import { useT } from "../lib/i18n/provider";

/**
 * Writing the imprint and the privacy policy.
 *
 * Both documents shipped as TSX components carrying `[placeholder]` markers for the
 * operator's name, address and contact details, which meant that publishing a legal
 * notice for a real deployment required editing source and rebuilding an image.
 * Anyone who does not do that was running a public service whose imprint named
 * nobody — the condition § 5 DDG exists to prevent.
 *
 * **Markdown, and raw HTML is not rendered.** These pages are the only ones served
 * without a session, and the CSP still allows `'unsafe-inline'` in `script-src`, so
 * stored HTML would be stored script on the least-authenticated page in the
 * product. `react-markdown` escapes raw HTML by default; the preview below is the
 * same component the public page uses, so what is shown here is what is published,
 * including HTML that will appear as visible text rather than as markup.
 *
 * **Both languages are saved in one call.** While the documents were code, rule 16's
 * promise that the two halves change together was enforced by the type system: the
 * sections were typed `Record<SectionId, ReactNode>` in both languages, so a section
 * present in German and missing in English was a compile error. Nothing typechecks a
 * database row, so the closest available guarantee is that one save covers both
 * halves and one timestamp describes them.
 */

const SLUGS = ["imprint", "privacy"] as const;
type Slug = (typeof SLUGS)[number];

interface LegalDocument {
  slug: Slug;
  body_de: string | null;
  body_en: string | null;
  source: "custom" | "default";
  updated_at: string | null;
}

type Draft = { body_de: string; body_en: string };

export default function LegalDocumentAdmin({ apiBase }: { apiBase: string }) {
  const t = useT();
  const [documents, setDocuments] = useState<LegalDocument[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [openSlug, setOpenSlug] = useState<Slug | null>(null);
  const [language, setLanguage] = useState<"de" | "en">("de");
  const [preview, setPreview] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<Slug | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/legal/documents`);
      if (res.status === 403) {
        // A member simply cannot edit these. An explanation, not an error.
        setDocuments([]);
        setError(t("legalAdmin.forbidden"));
        return;
      }
      if (!res.ok) throw new Error(t("legalAdmin.loadFailed"));
      const body = (await res.json()) as { documents?: LegalDocument[] };
      const list = body.documents ?? [];
      setDocuments(list);
      setDrafts(
        Object.fromEntries(
          list.map((doc) => [doc.slug, { body_de: doc.body_de ?? "", body_en: doc.body_en ?? "" }]),
        ),
      );
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [apiBase, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (slug: Slug) => {
    const draft = drafts[slug];
    if (!draft) return;
    setBusy(true);
    setError("");
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/legal/documents/${slug}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body_de: draft.body_de, body_en: draft.body_en }),
      });
      if (!res.ok) {
        // The server answers in English and states the reason (rule 17); the one
        // refusal this form can provoke is English text with no German text.
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail || t("legalAdmin.saveFailed"));
      }
      const updated = (await res.json()) as LegalDocument;
      setDocuments((current) =>
        current.map((doc) => (doc.slug === slug ? updated : doc)),
      );
      setSaved(slug);
      setTimeout(() => setSaved(null), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const titleKey = (slug: Slug) =>
    slug === "imprint" ? ("footer.imprint" as const) : ("footer.privacy" as const);

  return (
    <section className="space-y-4">
      <div className="flex items-start gap-2.5">
        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-brand" aria-hidden="true" />
        <div>
          <h3 className="text-sm font-bold text-ink">{t("legalAdmin.title")}</h3>
          <p className="mt-0.5 text-xs text-ink-muted">{t("legalAdmin.lead")}</p>
        </div>
      </div>

      {loading && <p className="text-xs text-ink-muted">{t("common.pleaseWait")}</p>}

      {error && (
        <p
          role="alert"
          className="rounded-2xl border border-danger-line bg-danger-soft px-3 py-2 text-xs font-semibold text-danger-ink-on-soft"
        >
          {error}
        </p>
      )}

      {documents.map((doc) => {
        const draft = drafts[doc.slug] ?? { body_de: "", body_en: "" };
        const open = openSlug === doc.slug;
        const body = language === "de" ? draft.body_de : draft.body_en;

        return (
          <div key={doc.slug} className="rounded-2xl border border-line bg-surface p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className="block text-xs font-bold text-ink">{t(titleKey(doc.slug))}</span>
                <span className="mt-0.5 block text-meta text-ink-muted">
                  {doc.source === "custom"
                    ? t("legalAdmin.stateCustom")
                    : t("legalAdmin.stateDefault")}
                </span>
              </div>
              <button
                type="button"
                onClick={() => {
                  setOpenSlug(open ? null : doc.slug);
                  setPreview(false);
                }}
                className="flex items-center gap-1.5 rounded-2xl border border-line bg-surface-muted px-4 py-2 text-xs font-bold text-ink-secondary transition-colors hover:bg-surface"
              >
                <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                {open ? t("common.close") : t("legalAdmin.edit")}
              </button>
            </div>

            {open && (
              <div className="mt-3 space-y-3 border-t border-line pt-3">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex rounded-2xl border border-line bg-surface-muted p-1 text-xs">
                    {(["de", "en"] as const).map((lang) => (
                      <button
                        key={lang}
                        type="button"
                        onClick={() => setLanguage(lang)}
                        className={`rounded-xl px-4 py-2 font-bold ${
                          language === lang
                            ? "bg-brand text-brand-ink shadow-sm"
                            : "text-ink-muted hover:text-ink"
                        }`}
                      >
                        {lang === "de" ? t("legalAdmin.german") : t("legalAdmin.english")}
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={() => setPreview((current) => !current)}
                    className="flex items-center gap-1.5 rounded-2xl border border-line bg-surface-muted px-4 py-2 text-xs font-bold text-ink-secondary transition-colors hover:bg-surface"
                  >
                    <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                    {preview ? t("legalAdmin.write") : t("legalAdmin.preview")}
                  </button>
                </div>

                <p className="text-meta leading-relaxed text-ink-muted">
                  {language === "de" ? t("legalAdmin.germanHint") : t("legalAdmin.englishHint")}
                </p>

                {preview ? (
                  /* The public page's own renderer, so the preview cannot flatter
                     the result: raw HTML shows here as text exactly as it will
                     there. */
                  <div className="legal-prose max-h-96 overflow-y-auto rounded-2xl border border-line bg-page p-4">
                    {body.trim() ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
                    ) : (
                      <p className="text-xs text-ink-muted">{t("legalAdmin.previewEmpty")}</p>
                    )}
                  </div>
                ) : (
                  <textarea
                    value={body}
                    onChange={(event) =>
                      setDrafts((current) => ({
                        ...current,
                        [doc.slug]: {
                          ...draft,
                          [language === "de" ? "body_de" : "body_en"]: event.target.value,
                        },
                      }))
                    }
                    rows={18}
                    spellCheck={false}
                    placeholder={t("legalAdmin.placeholder")}
                    className="w-full rounded-2xl border border-line bg-page px-4 py-3 font-mono text-xs leading-relaxed text-ink outline-none focus-ring"
                  />
                )}

                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-meta leading-relaxed text-ink-muted">
                    {t("legalAdmin.emptyMeansDefault")}
                  </p>
                  <button
                    type="button"
                    onClick={() => void save(doc.slug)}
                    disabled={busy}
                    className="rounded-2xl bg-brand px-5 py-2.5 text-xs font-bold text-brand-ink shadow-md shadow-brand/20 transition-colors hover:bg-brand-hover disabled:opacity-50"
                  >
                    {busy ? t("common.saving") : t("common.save")}
                  </button>
                </div>

                {saved === doc.slug && (
                  <p className="flex items-center gap-2 rounded-2xl border border-ok-line bg-ok-soft px-3 py-2 text-xs font-semibold text-ok-ink">
                    <ShieldCheck className="h-4 w-4 text-ok" aria-hidden="true" />
                    {t("legalAdmin.saved")}
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
