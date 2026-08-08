# Dashboard image.
#
# Bun, for install and at runtime. It replaced a mixed state that had gone wrong
# quietly: this Dockerfile installed with `pnpm install --frozen-lockfile` against
# a `pnpm-lock.yaml` that had gone stale -- `leaflet`, `@types/leaflet` and
# `@playwright/test` were added to package.json without regenerating it -- while CI
# installed with `npm ci` from `package-lock.json`. Two lockfiles, two answers, and
# an image that had been unbuildable for some time with nothing to say so, because
# nothing built it. There is one lockfile now, `bun.lock`, read by one tool, here
# and in CI.
#
# The runtime stage ships Next's standalone output rather than node_modules: 20 MB
# of traced server code instead of 522 MB of installed packages. See the comment on
# `output: "standalone"` in next.config.ts for why pruning the alternative by hand
# does not work.

FROM oven/bun:1-alpine AS deps

WORKDIR /app
COPY package.json bun.lock ./
# --frozen-lockfile: build what the lockfile says, and fail rather than quietly
# resolving to something that was never tested. This is the check that would have
# caught the stale lockfile years earlier than the first release attempt did.
RUN bun install --frozen-lockfile

FROM oven/bun:1-alpine AS builder

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . ./

# Next.js inlines NEXT_PUBLIC_* into the client bundle at build time, so it cannot
# be configured on the running container -- setting it in docker-compose.prod.yml
# does nothing. The published release image is therefore built *without* it, and
# the UI falls back to `window.location.origin` (see getApiBase in
# src/app/page.tsx), which is Traefik, which routes /api to the Gateway. One image
# then works for every host.
#
# The build arg exists for the case that does not fit: a UI served from a
# different origin than its API.
#
#     docker build --build-arg NEXT_PUBLIC_API_URL=https://api.example.com .
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1

RUN bun run build

# Regenerated here rather than trusted from the checkout, so the notices describe
# the tree that was actually installed. --check in CI keeps the committed copy
# honest; see scripts/generate-notices.ts for why this file has to exist at all.
RUN bun run notices

FROM oven/bun:1-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
# Standalone's server binds HOSTNAME, and a container that binds loopback answers
# nobody. Explicit rather than relying on the default.
ENV HOSTNAME=0.0.0.0
ENV NEXT_TELEMETRY_DISABLED=1

# The traced server, plus the two things tracing deliberately does not cover:
# the client-side chunks and the public assets, which are served as files rather
# than reached through an import.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

# MIT, BSD-2-Clause and ISC each require their copyright notice to accompany a
# copy, and an image is a copy. The full node_modules used to satisfy that by
# accident with its 271 licence files; standalone tracing copies JavaScript only,
# so this file carries them instead -- including the two self-hosted webfonts,
# which no dependency tree ever accounted for.
# The project's own licence is not copied here -- the build context is
# apps/dashboard and LICENSE lives at the repository root, out of reach. Every
# image carries it as an OCI label instead
# (org.opencontainers.image.licenses, set in the release workflow), and this
# file's header names it.
COPY --from=builder /app/THIRD-PARTY-NOTICES.txt ./THIRD-PARTY-NOTICES.txt

# next.config.ts is not copied, and standalone does not need it: the resolved
# configuration is baked into .next/required-server-files.json, so the security
# headers and the CSP from next.config.ts apply as the values they had at build
# time. Re-evaluating that file at runtime, against an environment where
# ALLOWED_ORIGINS and friends are unset, would silently produce a different CSP
# than the one that was built and tested.

EXPOSE 3000

CMD ["bun", "server.js"]
