FROM python:3.12-slim AS builder

WORKDIR /app
ENV PYTHONPATH=/app/src

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml

COPY src/ ./src/

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
