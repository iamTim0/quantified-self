# Documentation site — built once, served as static files.
#
# The dev setup runs `mkdocs serve` (a development server) against a read-only
# mount of the *entire repository*, including the committed .env. That is fine for
# local iteration and wrong for anything else, which is why production gets this
# instead: only docs/ and mkdocs.yml enter the build, and only the rendered HTML is
# shipped.

FROM python:3.12-slim AS build

WORKDIR /build

RUN pip install --no-cache-dir \
      "mkdocs>=1.6" \
      "mkdocs-material>=9.5"

COPY mkdocs.yml ./
COPY docs/ ./docs/

# --strict fails the build on broken internal links and nav problems, so a
# documentation regression cannot ship silently.
RUN mkdocs build --strict --site-dir /site

FROM nginx:1.27-alpine AS runtime

COPY --from=build /site /usr/share/nginx/html

# Traefik strips the /docs prefix, so the site is served from the root here.
RUN printf '%s\n' \
  'server {' \
  '  listen 8003;' \
  '  root /usr/share/nginx/html;' \
  '  index index.html;' \
  '  location / { try_files $uri $uri/ $uri.html /404.html; }' \
  '  location = /healthz { return 200 "ok"; add_header Content-Type text/plain; }' \
  '}' > /etc/nginx/conf.d/default.conf

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8003/healthz || exit 1
