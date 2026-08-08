# Built from the repository root, not from services/importers/weather.
#
# The importer resolves every metric name and unit through packages/shared-schemas,
# and a path dependency cannot be resolved from outside the build context. The COPY
# layout preserves the repository's relative structure so
# `../../../packages/shared-schemas` in pyproject.toml resolves the same way inside
# the image as it does on a developer's machine -- the same reason Core builds from
# the root for packages/proto.
#
# Build:  docker build -f services/importers/weather/Dockerfile .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency manifests first so a source-only change does not re-resolve.
COPY packages/shared-schemas/pyproject.toml ./packages/shared-schemas/
COPY packages/shared-schemas/src ./packages/shared-schemas/src
COPY services/importers/weather/pyproject.toml services/importers/weather/uv.lock ./services/importers/weather/

WORKDIR /app/services/importers/weather
# --frozen: build what the lockfile says, and fail rather than silently
# re-resolving to something that was never tested.
RUN uv sync --frozen --no-install-project

COPY services/importers/weather/src/ ./src/
RUN uv sync --frozen

ENV PATH="/app/services/importers/weather/.venv/bin:${PATH}"

CMD ["python", "-m", "weather_importer.main"]
