FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system .

COPY src/ src/

CMD ["python", "-m", "yazio_importer.main"]
