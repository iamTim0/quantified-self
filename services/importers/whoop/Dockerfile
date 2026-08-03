FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app/src
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
RUN uv pip install --system -r pyproject.toml
COPY src ./src
CMD ["python", "-m", "whoop_importer.main"]
