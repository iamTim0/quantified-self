# Built from the repository root, not from services/core.
#
# Core depends on packages/proto for the gRPC stubs and on packages/shared-schemas for
# the metric registry, and a path dependency cannot be resolved from outside the build
# context. The COPY layout preserves the repository's relative structure so
# `../../packages/proto` and `../../packages/shared-schemas` in pyproject.toml resolve
# the same way inside the image as they do on a developer's machine.
#
# The shared-schemas lines were missing for a while, and the way that stayed hidden is
# worth knowing: nothing in CI builds this image -- the release workflow is the first
# thing that ever does -- and a cached `uv sync` layer from before the dependency existed
# kept answering, so `docker compose up --build` succeeded until something finally
# invalidated it. Then it failed with `Distribution not found at:
# file:///app/packages/shared-schemas`, which reads like a broken checkout rather than a
# missing COPY. tools/tests/test_build_images.py now checks every Dockerfile against its
# service's declared path dependencies.
#
# Build:  docker build -f services/core/Dockerfile .
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency manifests first so a source-only change does not re-resolve.
COPY packages/proto/pyproject.toml ./packages/proto/
COPY packages/proto/gen ./packages/proto/gen
COPY packages/shared-schemas/pyproject.toml ./packages/shared-schemas/
COPY packages/shared-schemas/src ./packages/shared-schemas/src
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
