# Built from the repository root, not from services/core.
#
# Core depends on packages/proto for the gRPC stubs, and a path dependency cannot
# be resolved from outside the build context. The COPY layout preserves the
# repository's relative structure so `../../packages/proto` in pyproject.toml
# resolves the same way inside the image as it does on a developer's machine.
#
# Build:  docker build -f services/core/Dockerfile .
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency manifests first so a source-only change does not re-resolve.
COPY packages/proto/pyproject.toml ./packages/proto/
COPY packages/proto/gen ./packages/proto/gen
COPY services/core/pyproject.toml services/core/uv.lock ./services/core/

WORKDIR /app/services/core
# --frozen: build what the lockfile says, and fail rather than silently
# re-resolving to something that was never tested.
RUN uv sync --frozen --no-install-project

COPY services/core/alembic.ini ./
COPY services/core/alembic/ ./alembic/
COPY services/core/src/ ./src/
RUN uv sync --frozen

ENV PATH="/app/services/core/.venv/bin:${PATH}"

# 8001 is HTTP; 50051 is the gRPC read API the Analysis Service uses.
EXPOSE 8001 50051

CMD ["uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8001"]
