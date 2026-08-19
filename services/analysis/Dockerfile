# Built from the repository root, not from services/analysis -- see the comment
# in services/core/Dockerfile for why (the packages/proto path dependency).
#
# Build:  docker build -f services/analysis/Dockerfile .
FROM node:26-slim AS codex

# Pinned because the stdio JSONL and dynamic-tool schemas are the runtime
# contract used by analysis.codex_app_server.
RUN npm install --global @openai/codex@0.146.1

FROM python:3.14-slim AS builder

# node(1) links against libatomic, which the node image ships and python:3.14-slim
# does not. Without it the interpreter dies in the loader before running a line, so
# `codex app-server` writes no handshake, the initialize request times out, and the
# chat answers CODEX_UNAVAILABLE -- indistinguishable from a CLI that was never
# installed, because `codex` itself does resolve on PATH.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && apt-get clean

# The official package selects the native binary for the image architecture.
# Copying Node plus the installed package keeps npm and its cache out of the
# runtime image while making `codex app-server` available.
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules/@openai /usr/local/lib/node_modules/@openai
RUN ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
# Fail the build instead of publishing an image whose chat is dead on arrival.
RUN codex --version

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY packages/proto/pyproject.toml ./packages/proto/
COPY packages/proto/gen ./packages/proto/gen
# The metric registry, for each metric's expected cadence. A path dependency the
# image does not carry fails the build with "Distribution not found", which is
# what tools/tests/test_build_images.py exists to catch before CI does.
COPY packages/shared-schemas/pyproject.toml ./packages/shared-schemas/
COPY packages/shared-schemas/src ./packages/shared-schemas/src
COPY services/analysis/pyproject.toml services/analysis/uv.lock ./services/analysis/

WORKDIR /app/services/analysis
RUN uv sync --frozen --no-install-project

COPY services/analysis/src/ ./src/
RUN uv sync --frozen

ARG SOURCE_VERSION=dev
ARG SOURCE_COMMIT=unknown
ENV QS_SERVICE_VERSION=$SOURCE_VERSION
ENV QS_SOURCE_COMMIT=$SOURCE_COMMIT
ENV PATH="/app/services/analysis/.venv/bin:${PATH}"

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=3)"

CMD ["uvicorn", "analysis.main:app", "--host", "0.0.0.0", "--port", "8010"]
