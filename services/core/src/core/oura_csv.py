"""Validation and normalization for Oura CSV uploads."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone

MAX_CSV_ROWS = 10_000
_METRIC_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_TIMESTAMP_COLUMNS = ("timestamp", "date", "day")
_VALUE_COLUMNS = ("value", "score")


class CsvImportValidationError(ValueError):
    """Raised when an uploaded Oura CSV cannot be imported safely."""


@dataclass(frozen=True)
class CsvMetricPoint:
    """A normalized metric read from a single CSV row."""

    timestamp: datetime
    metric_type: str
    value: float
    metadata: dict[str, str]


def normalize_metric_type(value: str) -> str:
    """Validate a metric type accepted by the public CSV upload API."""
    normalized = value.strip().lower().replace(" ", "_")
    if not _METRIC_TYPE_PATTERN.fullmatch(normalized):
        raise CsvImportValidationError(
            "Metric types must start with a letter and contain only lowercase letters, numbers, or underscores."
        )
    return normalized


def make_idempotency_key(tenant_id: str, source_id: str, metric_type: str, timestamp: datetime) -> str:
    """Create the deterministic key required for exact-once CSV imports."""
    canonical_timestamp = timestamp.astimezone(timezone.utc).isoformat()
    raw_key = f"{tenant_id}:{source_id}:{metric_type}:{canonical_timestamp}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def parse_oura_csv(csv_content: str, default_metric_type: str) -> list[CsvMetricPoint]:
    """Parse supported Oura CSV exports without persisting any uploaded content."""
    if not csv_content.strip():
        raise CsvImportValidationError("The CSV file is empty.")

    default_metric_type = normalize_metric_type(default_metric_type)
    try:
        dialect = csv.Sniffer().sniff(csv_content[:4096], delimiters=",;")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(csv_content), dialect=dialect)
    if not reader.fieldnames:
        raise CsvImportValidationError("The CSV file must include a header row.")

    normalized_headers = {
        header: header.strip().lower().replace(" ", "_")
        for header in reader.fieldnames
        if header is not None
    }
    available_headers = set(normalized_headers.values())
    if not available_headers.intersection(_TIMESTAMP_COLUMNS):
        raise CsvImportValidationError("The CSV requires one of these date columns: timestamp, date, or day.")
    if not available_headers.intersection(_VALUE_COLUMNS):
        raise CsvImportValidationError("The CSV requires a value or score column.")

    points: list[CsvMetricPoint] = []
    recognized_columns = set(_TIMESTAMP_COLUMNS) | set(_VALUE_COLUMNS) | {"metric_type"}
    for row_number, raw_row in enumerate(reader, start=2):
        if len(points) >= MAX_CSV_ROWS:
            raise CsvImportValidationError(f"A CSV upload may contain at most {MAX_CSV_ROWS} data rows.")

        row = {
            normalized_headers[header]: (value or "").strip()
            for header, value in raw_row.items()
            if header is not None
        }
        if not any(row.values()):
            continue

        timestamp_raw = next((row[column] for column in _TIMESTAMP_COLUMNS if row.get(column)), "")
        value_raw = next((row[column] for column in _VALUE_COLUMNS if row.get(column)), "")
        if not timestamp_raw or not value_raw:
            raise CsvImportValidationError(f"Row {row_number} requires a date and a value.")

        try:
            timestamp = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CsvImportValidationError(f"Row {row_number} has an invalid ISO date or timestamp.") from exc
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        try:
            value = float(value_raw)
        except ValueError as exc:
            raise CsvImportValidationError(f"Row {row_number} has a non-numeric value.") from exc

        metric_type = normalize_metric_type(row.get("metric_type") or default_metric_type)
        metadata = {
            column: value
            for column, value in row.items()
            if column not in recognized_columns and value
        }
        points.append(
            CsvMetricPoint(
                timestamp=timestamp.astimezone(timezone.utc),
                metric_type=metric_type,
                value=value,
                metadata=metadata,
            )
        )

    if not points:
        raise CsvImportValidationError("The CSV contains no data rows.")
    return points
