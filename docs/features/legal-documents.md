# Legal texts

## Purpose

The imprint and the privacy policy are the only two pages this platform serves to
readers who are not signed in, and they are the two whose content is a legal obligation
rather than a product decision. This feature makes them **text the operator writes**,
stored in the database and editable in the dashboard, instead of source code.

Before it, both documents existed only as TSX components carrying `[placeholder]`
markers for the company name, the address and the contact details. Filling them in meant
editing `apps/dashboard/src/app/legal/` and rebuilding the dashboard image. Anyone
running this platform who does not do that was serving a public legal notice that
identified nobody — the exact condition § 5 DDG exists to prevent.

**Those templates no longer ship.** A page that names a placeholder company is not a
weaker notice than an empty one, it is a wrong one: a reader cannot tell invented
provider details from real ones, while a page saying the document has not been
published is unambiguous to a reader and to the operator who sees it. Until the
operator writes a text, that is what both routes say.

## Markdown, and why not HTML

Documents are written in **Markdown**. Raw HTML inside them is escaped and appears as
visible text; it is never rendered.

That is a security decision, not a taste one. These two routes are the only pages served
without a session, and the dashboard's Content-Security-Policy still permits
`'unsafe-inline'` in `script-src` — a gap `next.config.ts` documents rather than hides.
Storing HTML here would mean storing executable script on the widest-reach,
least-authenticated page in the product, and it would put a sanitiser on the critical
path of a statutory notice for as long as the feature exists. Markdown removes the
question instead of answering it: `react-markdown` does not pass raw HTML through unless
`rehype-raw` is added, so the safe behaviour is the default one.

What Markdown gives up is nothing a legal text uses. Headings, paragraphs, lists,
tables, links and emphasis are the whole vocabulary of both documents, and GitHub
Flavoured Markdown covers all of it. The rendered output lands on the same
`.legal-prose` styles the legal routes already use, so a written document inherits the
same typography rather than a second, drifting set of rules.

## What a reader sees

| State | German reader | English reader |
| --- | --- | --- |
| Nothing written | The document title and one sentence: the operator has not published it | The same, in English |
| German written, no English | The German text | The German text, with a note that the document is published in German only |
| Both written | The German text | The English text, with the courtesy-translation note |

The middle row is the decision worth stating. An English reader is shown **German text**
rather than the not-published notice, because the operator *has* published a document and
withholding it over its language serves nobody. A current document in the wrong language
is the lesser failure, and the note says so — rule 16 of `AGENTS.md` makes the same
argument for the two halves of a legal text.

German never falls back to English: it is the binding half, so there is no case where
showing the courtesy translation in its place is right.

**Clearing the German text withdraws the document.** Emptying a field is how an operator
takes a text down, and it is why an empty save is accepted rather than refused.
Saving English text while the German field is empty *is* refused, with a 422 that says
why — the binding half cannot be the missing one.

## How it flows

```text
Dashboard (owner)                Core                        Public reader
     │                            │                                │
     ├─ PUT /api/v1/data/legal/documents/{slug} ──▶ legal_documents │
     │        (JWT, owner/admin)  │                                │
     │                            ◀── GET /api/v1/legal/documents/{slug} ─┤
     │                            │        (no session)            │
```

`legal_documents` is **deployment-wide and has no `tenant_id`**, which is a decision
rather than an oversight about rule 2. An imprint identifies whoever operates the
service; there is no workspace inside a deployment that could own one, and the pages are
read by visitors for whom no tenant exists. `oidc_providers` is unscoped for the same
reason.

Writing is guarded by `require_platform_admin`, not by `require_role`. The distinction is the whole
security model of this feature: every account-creation path in Core mints an owner, so on a deployment
with registration enabled, a role check alone would have let anybody who signed up rewrite the imprint
and privacy policy that every visitor reads. The check additionally requires the caller's workspace to
be the deployment's — the oldest one, or whichever `PLATFORM_TENANT_ID` names.

The read endpoint is exempt from Core's authentication middleware and has its own
unauthenticated route on the Gateway. It is spelled out rather than taken as a prefix:
writing lives under `/api/v1/data/legal/`, where it is authenticated like everything
else, and a wildcard is how the write path would have quietly become public too.

The legal pages fetch on the **server**, while rendering. That keeps the two properties
those routes already had — the document is in the first response, in the reader's
language, and the page needs no JavaScript. It also means the dashboard container needs
an address for the API of its own: `INTERNAL_API_URL`, set to `http://api-gateway:8000`
in both Compose files. The code default is `http://127.0.0.1:8000`, which is loopback and
the port the Gateway actually binds (rule 18).

If that request fails or times out, the page renders the not-published notice rather than
an error. A legal page whose API is down must still render; an error page where a
statutory notice belongs is the worse outcome, and it arrives exactly when the platform is
already having a bad day.

## Using it

1. Sign in as an owner or administrator **of the platform workspace** and open **Profile**.
   These documents belong to the deployment rather than to a workspace, so a role alone is not
   enough — see [The platform workspace](../operations.md#the-platform-workspace).
2. Under **Legal texts**, open *Imprint* or *Privacy policy*.
3. Write the German version. **Preview** renders it with the same component the public
   page uses, so what is previewed is what is published — including HTML, which appears
   as text.
4. Optionally add the English version.
5. Save. The public page shows the new text on the next request; nothing is cached.

The editor states whether a text of your own is published or nothing is, so "we never
put an imprint up" is visible rather than something to remember.

## Limitations

- **The set of documents is closed**: `imprint` and `privacy`. Each is a statutory
  obligation with a route of its own, not a page an operator invents. Arbitrary
  additional legal pages would need routing, footer navigation and slug handling that do
  not exist.
- **There is no version history.** The table keeps the current text, who saved it last
  and when. A privacy policy that changed materially is something a controller may need
  to evidence, and this does not evidence it — keep your own record.
- **Nothing validates the content.** The platform cannot know whether an imprint
  satisfies § 5 DDG, and it does not pretend to. These texts are no substitute for legal
  advice: have them reviewed by a qualified party before production use.
- **A deployment with nothing written publishes no imprint and no privacy policy.** That
  is a statutory gap the platform cannot close for you, and it is why the pages say so
  plainly instead of filling the space with a template.
- **Rolling back migration `028_legal_documents` deletes the text**, and both pages return
  to the not-published notice. Export both documents first.

## Retrieving a document

```http
GET /api/v1/legal/documents/privacy
```

No authentication. Returns the two Markdown bodies, `source` (`custom` or `default`) and
`updated_at`. `source` is the field that matters: `custom` means at least one language was
written, `default` means nothing is published — a distinction two empty bodies do not make
on their own.
