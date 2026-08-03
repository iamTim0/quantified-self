FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app/src

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml README.md ./
RUN uv pip install --system -r pyproject.toml

COPY src/ ./src/

CMD ["python", "-m", "dawarich_importer.main"]
