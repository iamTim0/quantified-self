import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * An operator-written legal document, rendered.
 *
 * **Markdown, and raw HTML deliberately not passed through.** These two routes are
 * the only pages this product serves to a reader with no session, and the CSP still
 * permits `'unsafe-inline'` in `script-src` — a gap `next.config.ts` documents
 * rather than hides. Storing HTML here would therefore be storing executable script
 * on the widest-reach, least-authenticated page in the platform, and it would put a
 * sanitiser on the critical path of a statutory notice forever. `react-markdown`
 * escapes raw HTML unless `rehype-raw` is added, so the safe behaviour is the
 * default one and nothing downstream has to be trusted.
 *
 * Nothing is passed for `components`. The surrounding `.legal-prose` styles plain
 * `h1`/`h2`/`p`/`ul`/`table` — which is exactly what this emits — so the written
 * document inherits the same typography as the shipped one instead of a second,
 * drifting set of rules.
 *
 * A server component: `react-markdown` renders without state or effects, so the
 * page keeps the property its predecessor had of needing no JavaScript at all.
 */
export default function LegalMarkdown({ body }: { body: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
  );
}
