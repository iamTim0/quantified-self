"""
Shared Python schemas for Quantified Self platform.
"""

from .aggregation import (
    aggregate_events,
    aggregate_stream,
    bucket_timestamp,
    default_policies,
)
from .data_point import provenance
from .events import IngestEvent, idempotency_key
from .field_report import (
    MAX_TRACKED_PATHS,
    FieldReport,
    FieldReportCollector,
    FieldSighting,
    value_kind,
)
from .metrics import (
    CANONICAL_KEYS,
    DYNAMIC_NAMESPACES,
    METRIC_ALIASES,
    METRIC_CATALOG,
    Aggregation,
    IngestResolution,
    MetricCategory,
    MetricDefinition,
    MetricNamespace,
    MetricUnit,
    UnknownMetricTypeError,
    UnsupportedConversionError,
    canonical_metric_type,
    convert,
    describe,
    is_known_metric_type,
    metrics_for_source,
)
from .upload_spool import (
    DEFAULT_CHUNK_BYTES,
    DEFAULT_TTL_SECONDS,
    OffsetMismatch,
    SpoolTooLarge,
    UnknownUpload,
    UploadSession,
    UploadSpool,
    UploadSpoolError,
)

__all__ = [
    "CANONICAL_KEYS",
    "DEFAULT_CHUNK_BYTES",
    "DEFAULT_TTL_SECONDS",
    "DYNAMIC_NAMESPACES",
    "MAX_TRACKED_PATHS",
    "METRIC_ALIASES",
    "METRIC_CATALOG",
    "Aggregation",
    "FieldReport",
    "FieldReportCollector",
    "FieldSighting",
    "IngestEvent",
    "IngestResolution",
    "MetricCategory",
    "MetricDefinition",
    "MetricNamespace",
    "MetricUnit",
    "OffsetMismatch",
    "SpoolTooLarge",
    "UnknownMetricTypeError",
    "UnknownUpload",
    "UnsupportedConversionError",
    "UploadSession",
    "UploadSpool",
    "UploadSpoolError",
    "aggregate_events",
    "aggregate_stream",
    "bucket_timestamp",
    "canonical_metric_type",
    "convert",
    "default_policies",
    "describe",
    "idempotency_key",
    "is_known_metric_type",
    "metrics_for_source",
    "provenance",
    "value_kind",
]
