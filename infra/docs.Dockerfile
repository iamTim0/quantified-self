# Documentation site — built once, served as static files.
#
# The dev setup runs `mkdocs serve` (a development server) against a read-only
# mount of the *entire repository*, including the committed .env. That is fine for
# local iteration and wrong for anything else, which is why production gets this
# instead: only docs/ and mkdocs.yml enter the build, and only the rendered HTML is
# shipped.

FROM python:3.14-slim AS build

WORKDIR /build

RUN pip install --no-cache-dir \
      "mkdocs>=1.6" \
      "mkdocs-material>=9.5"

COPY mkdocs.yml ./
COPY docs/ ./docs/

# --strict fails the build on broken internal links and nav problems, so a
# documentation regression cannot ship silently.
RUN mkdocs build --strict --site-dir /site

FROM nginx:1.31-alpine AS runtime

# Under /docs, not at the root, because that is the path the site is *addressed*
# at from the outside and nginx redirects with paths of its own. See the server
# block below.
COPY --from=build /site /usr/share/nginx/html/docs

ARG SOURCE_VERSION=dev
ARG SOURCE_COMMIT=unknown
RUN printf '{"status":"ok","service":"qs-docs","version":"%s","commit":"%s"}\n' \
      "$SOURCE_VERSION" "$SOURCE_COMMIT" > /usr/share/nginx/html/health.json

# The site is served under /docs, Traefik hands the prefix through unstripped, and
# **nothing here redirects**. Both properties are load-bearing and were learned
# the same way -- from a documentation site that had become unreachable.
#
# The prefix stays because a proxy cannot put a stripped prefix back into a
# Location header: with /docs removed, nginx composed its redirects from the only
# things it knew, and a click produced `http://<host>:8003/metrics/` -- the wrong
# port, plain http behind TLS, no prefix. `absolute_redirect off` keeps whatever
# does redirect to a bare path resolved against the origin in the address bar.
#
# The redirects themselves are gone because MkDocs now publishes file URLs
# (`use_directory_urls: false`), so there is no directory to add a slash to. That
# removed the last dependency on a trailing slash surviving the trip -- and it did
# not survive: a rule at the CDN edge rewrote `/docs/metrics/` to `/docs/metrics`
# before the request arrived, nginx answered the 301 to the slashed form that
# directory URLs require, the edge stripped it again, and the browser gave up with
# ERR_TOO_MANY_REDIRECTS. Nothing in this stack could see it; the origin log was
# the only place the missing slash was visible.
#
# So a page resolves from three spellings and redirects for none of them:
# `/docs/metrics.html` is the file, `/docs/metrics` finds it through `$uri.html`,
# and the legacy directory form `/docs/metrics/` is the one case that still
# answers 301 -- to the *unslashed* URL, which no slash-stripping proxy can bounce
# back. `/healthz` stays at the root for the HEALTHCHECK and the gateway probe.
#
# A missing page answers 404 and *renders* the styled page, via `error_page`
# rather than as the last entry of `try_files`. Naming the file there serves it
# with status 200, which is not a detail: probing this deployment, `/docs/healthz`
# and `/docs/docs/` both answered 200 with the 404 page, and that read as proof
# that a prefix was being stripped when nothing of the sort was happening.
RUN printf '%s\n' \
  'server {' \
  '  listen 8003;' \
  '  root /usr/share/nginx/html;' \
  '  index index.html;' \
  '  absolute_redirect off;' \
  '  location = / { return 301 /docs; }' \
  '  location = /docs { try_files /docs/index.html =404; }' \
  '  location = /docs/ { try_files /docs/index.html =404; }' \
  '  location = /healthz {' \
  '    default_type application/json;' \
  '    add_header Cache-Control "no-store";' \
  '    try_files /health.json =404;' \
  '  }' \
  '  location ~ ^(/docs/.+)/$ { return 301 $1; }' \
  '  error_page 404 /docs/404.html;' \
  '  location / { try_files $uri $uri.html $uri/index.html =404; }' \
  '}' > /etc/nginx/conf.d/default.conf

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8003/healthz || exit 1
