# Built from the repository root, not from services/analysis -- see the comment
# in services/core/Dockerfile for why (the packages/proto path dependency).
#
# Build:  docker build -f services/analysis/Dockerfile .
FROM python:3.12-slim AS builder

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

ENV PATH="/app/services/analysis/.venv/bin:${PATH}"

EXPOSE 8010

CMD ["uvicorn", "analysis.main:app", "--host", "0.0.0.0", "--port", "8010"]
