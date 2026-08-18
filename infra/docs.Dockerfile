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

# The site is served under /docs, and Traefik hands the prefix through unstripped,
# because MkDocs' directory URLs make nginx a source of redirects: `try_files
# $uri $uri/` answers a request for a directory without a trailing slash with a
# 301 to the slashed form, and that redirect is built from what nginx itself
# knows. With the prefix stripped and the default `absolute_redirect on`, a click
# on /docs/metrics produced `Location: http://<host>:8003/metrics/` — the wrong
# port, the wrong scheme behind TLS, and no /docs at all. Nothing downstream can
# repair that: Traefik's StripPrefix does not rewrite Location headers back.
#
# The redirect itself is not the bug and must stay. Serving /docs/metrics
# directly instead would resolve every relative link on the page one level too
# high, because MkDocs writes them against the slashed URL.
#
# So: the prefix exists here too (`absolute_redirect off` then makes the Location
# a bare path, `/docs/metrics/`, which the browser resolves against the origin it
# is already on), and the development stack, where `mkdocs serve` serves under
# /docs/ for the same reason, now routes identically.
RUN printf '%s\n' \
  'server {' \
  '  listen 8003;' \
  '  root /usr/share/nginx/html;' \
  '  index index.html;' \
  '  absolute_redirect off;' \
  '  location = / { return 301 /docs/; }' \
  '  location / { try_files $uri $uri/ $uri.html /docs/404.html; }' \
  '  location = /healthz {' \
  '    default_type application/json;' \
  '    add_header Cache-Control "no-store";' \
  '    try_files /health.json =404;' \
  '  }' \
  '}' > /etc/nginx/conf.d/default.conf

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8003/healthz || exit 1
