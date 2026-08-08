# Built from the repository root, not from services/importers/yazio.
#
# The importer resolves every metric name and unit through packages/shared-schemas,
# and a path dependency cannot be resolved from outside the build context. The COPY
# layout preserves the repository's relative structure so
# `../../../packages/shared-schemas` in pyproject.toml resolves the same way inside
# the image as it does on a developer's machine -- the same reason Core builds from
# the root for packages/proto.
#
# Build:  docker build -f services/importers/yazio/Dockerfile .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency manifests first so a source-only change does not re-resolve.
COPY packages/shared-schemas/pyproject.toml ./packages/shared-schemas/
COPY packages/shared-schemas/src ./packages/shared-schemas/src
COPY services/importers/yazio/pyproject.toml services/importers/yazio/uv.lock ./services/importers/yazio/

WORKDIR /app/services/importers/yazio
# --frozen: build what the lockfile says, and fail rather than silently
# re-resolving to something that was never tested.
RUN uv sync --frozen --no-install-project

COPY services/importers/yazio/src/ ./src/
COPY services/importers/yazio/README.md ./
RUN uv sync --frozen

ENV PATH="/app/services/importers/yazio/.venv/bin:${PATH}"

CMD ["python", "-m", "yazio_importer.main"]
