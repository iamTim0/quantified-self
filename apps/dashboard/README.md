# Dashboard

The Next.js UI for the Quantified Self platform. This file replaced the
`create-next-app` boilerplate, which listed four package managers and a font
Vercel ships with its template — none of which applies here.

## One package manager: Bun

`bun.lock` is the only lockfile, and the same tool reads it in development, in CI
and in the image. That is deliberate: this app previously had a
`package-lock.json` *and* a `pnpm-lock.yaml`, CI installed from the first and the
Dockerfile from the second, and the pnpm one had gone stale — three dependencies
were added to `package.json` without regenerating it. The image was therefore
unbuildable for some time, and nothing failed, because nothing built it.

```bash
bun install               # honours bun.lock
bun run dev               # dev server on :3000
bun run build             # production build
bun run tsc --noEmit      # type check
bun run lint              # eslint
bunx playwright test      # browser tests — needs the stack up, see below
```

From the repository root, `task dashboard` runs the dev server and `task lint:all`
runs the type check and linter alongside the Python ones.

`trustedDependencies` in `package.json` lists the two packages whose install
scripts must run (`sharp`, `unrs-resolver`). Bun blocks lifecycle scripts unless a
package is named there; without it, image optimisation and ESLint's resolver get
installed but not built.

## The browser tests need a real stack

There is no `webServer` block in `playwright.config.ts` on purpose: this needs
Postgres, Core, Next *and* the Gateway, and the Gateway has to start last because
it proxies the other two. The tests run against the **Gateway's** origin, not the
Next server's, because that single origin is what makes the session cookies behave
as they do in production.

`.github/workflows/ci.yml` (the `browser` job) is the executable description of
that sequence; the docstring at the top of `playwright.config.ts` is the short one.

## What is worth knowing before editing

- **This is not the Next.js you may know.** Read the relevant guide under
  `node_modules/next/dist/docs/` before writing code; see `AGENTS.md` here.
- `NEXT_PUBLIC_*` is inlined at **build** time. The published image is built
  without `NEXT_PUBLIC_API_URL` so the UI calls `window.location.origin`, which is
  Traefik, which routes `/api` to the Gateway — one image for every deployment.
  Setting that variable on a running container does nothing.
- `src/proxy.ts` is the server-side route guard (Next 16's `middleware.ts`).
- `next.config.ts` sets `output: "standalone"`; the image ships the traced server
  (20 MB) instead of `node_modules` (522 MB).
