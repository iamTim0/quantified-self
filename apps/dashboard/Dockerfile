# Dashboard image.
#
# npm, not pnpm. This used to run `pnpm install --frozen-lockfile` against
# `pnpm-lock.yaml`, and that lockfile had gone stale: `leaflet`,
# `@types/leaflet` and `@playwright/test` were added to package.json without it
# being regenerated, so the build failed with ERR_PNPM_OUTDATED_LOCKFILE. Nothing
# noticed, because CI installs with `npm ci` from `package-lock.json` in all three
# jobs that touch this app -- so the only dependency set that is ever verified is
# npm's, and this image now builds from that same one. The Playwright suite that
# proves the built app works runs against it too.
#
# Three stages so the runtime image carries production dependencies only: the
# previous one shipped the builder's full node_modules, eslint, typescript,
# tailwind and @playwright/test included.

FROM node:22-alpine AS deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS builder

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

RUN npm run build

FROM node:22-alpine AS prod-deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM node:22-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json ./
COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next

# next.config.ts is deliberately not copied. `next start` reads the resolved
# configuration from .next/required-server-files.json, so the security headers and
# the CSP built in next.config.ts do apply -- as the values they had at build
# time. Shipping the file as well would have Next re-evaluate it against a runtime
# environment where ALLOWED_ORIGINS and friends are unset, silently producing a
# different CSP than the one that was built and tested.

EXPOSE 3000

CMD ["npm", "run", "start"]
