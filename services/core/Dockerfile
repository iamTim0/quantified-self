FROM python:3.12-slim AS builder

WORKDIR /app
ENV PYTHONPATH=/app/src

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml

COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY src/ ./src/

CMD ["uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8001"]
