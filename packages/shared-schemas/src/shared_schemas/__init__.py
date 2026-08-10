"""
Shared Python schemas for Quantified Self platform.
"""

from .data_point import DataPointQuery, DataPointRead
from .events import IngestEvent, IngestEventBatch, idempotency_key
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
from .tenant import ShareScope, TenantContext, TenantShareGrant
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
    "DataPointQuery",
    "DataPointRead",
    "FieldReport",
    "FieldReportCollector",
    "FieldSighting",
    "IngestEvent",
    "IngestEventBatch",
    "MetricCategory",
    "MetricDefinition",
    "MetricNamespace",
    "MetricUnit",
    "OffsetMismatch",
    "ShareScope",
    "SpoolTooLarge",
    "TenantContext",
    "TenantShareGrant",
    "UnknownMetricTypeError",
    "UnknownUpload",
    "UnsupportedConversionError",
    "UploadSession",
    "UploadSpool",
    "UploadSpoolError",
    "canonical_metric_type",
    "convert",
    "describe",
    "idempotency_key",
    "is_known_metric_type",
    "metrics_for_source",
    "value_kind",
]
