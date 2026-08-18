FROM python:3.14-slim AS builder

WORKDIR /app
ENV PYTHONPATH=/app/src

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml

COPY src/ ./src/

ARG SOURCE_VERSION=dev
ARG SOURCE_COMMIT=unknown
ENV QS_SERVICE_VERSION=$SOURCE_VERSION
ENV QS_SOURCE_COMMIT=$SOURCE_COMMIT
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
