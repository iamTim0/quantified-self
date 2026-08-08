"""
Shared Python schemas for Quantified Self platform.
"""

from .data_point import DataPointQuery, DataPointRead
from .events import IngestEvent, IngestEventBatch
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

__all__ = [
    "CANONICAL_KEYS",
    "DYNAMIC_NAMESPACES",
    "METRIC_ALIASES",
    "METRIC_CATALOG",
    "Aggregation",
    "DataPointQuery",
    "DataPointRead",
    "IngestEvent",
    "IngestEventBatch",
    "MetricCategory",
    "MetricDefinition",
    "MetricNamespace",
    "MetricUnit",
    "ShareScope",
    "TenantContext",
    "TenantShareGrant",
    "UnknownMetricTypeError",
    "UnsupportedConversionError",
    "canonical_metric_type",
    "convert",
    "describe",
    "is_known_metric_type",
    "metrics_for_source",
]
