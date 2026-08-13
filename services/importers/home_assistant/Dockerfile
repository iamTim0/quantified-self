# Built from the repository root, not from services/importers/home_assistant.
#
# The importer resolves every metric name and unit through packages/shared-schemas,
# and a path dependency cannot be resolved from outside the build context. The COPY
# layout preserves the repository's relative structure so
# `../../../packages/shared-schemas` in pyproject.toml resolves the same way inside
# the image as it does on a developer's machine -- the same reason Core builds from
# the root for packages/proto.
#
# Build:  docker build -f services/importers/home_assistant/Dockerfile .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency manifests first so a source-only change does not re-resolve.
COPY packages/shared-schemas/pyproject.toml ./packages/shared-schemas/
COPY packages/shared-schemas/src ./packages/shared-schemas/src
COPY services/importers/home_assistant/pyproject.toml services/importers/home_assistant/uv.lock ./services/importers/home_assistant/

WORKDIR /app/services/importers/home_assistant
# --frozen: build what the lockfile says, and fail rather than silently
# re-resolving to something that was never tested.
RUN uv sync --frozen --no-install-project

COPY services/importers/home_assistant/src/ ./src/
RUN uv sync --frozen

ENV PATH="/app/services/importers/home_assistant/.venv/bin:${PATH}"

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,socket; from urllib.parse import urlparse; u=urlparse(os.getenv('NATS_URL','nats://localhost:4222')); s=socket.create_connection((u.hostname or 'localhost',u.port or 4222),3); s.close()"

CMD ["python", "-m", "home_assistant_importer.main"]
