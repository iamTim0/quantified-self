"""Explicit one-shot rollup rebuild for data already stored before rollups existed."""

from __future__ import annotations

import argparse
import asyncio
import uuid

from shared_schemas.metrics import METRIC_CATALOG, Aggregation
from sqlalchemy import text

from core.db.session import async_session_maker


def _metric_list(aggregation: Aggregation) -> str:
    """Build a quoted SQL list from registry keys, never from user input."""
    return ", ".join(
        f"'{key}'" for key, definition in METRIC_CATALOG.items() if definition.aggregation is aggregation
    ) or "''"


async def rebuild(tenant_id: str) -> None:
    """Rebuild all three rollup resolutions for one tenant."""
    tenant_id = str(uuid.UUID(tenant_id))
    sum_keys = _metric_list(Aggregation.SUM)
    max_keys = _metric_list(Aggregation.MAX)
    last_keys = _metric_list(Aggregation.LAST)
    tenant_clause = "AND tenant_id = :tenant_id"

    async with async_session_maker() as session:
        for resolution in ("minute", "hour", "day"):
            provider_flag = "COALESCE(metadata->>'provider_total', 'false') = 'true'"
            provider_filter = "" if resolution == "day" else f"AND NOT ({provider_flag})"
            query = text(
                f"""
                WITH source_points AS (
                    SELECT
                        tenant_id,
                        source_id,
                        metric_type,
                        timestamp,
                        value,
                        {provider_flag} AS is_provider_total,
                        date_trunc(:resolution, timestamp) AS bucket_start
                    FROM data_points
                    WHERE value IS NOT NULL {tenant_clause} {provider_filter}
                ), grouped AS (
                    SELECT
                        tenant_id,
                        source_id,
                        metric_type,
                        bucket_start,
                        bool_or(is_provider_total AND metric_type IN ({sum_keys}))
                            AS has_provider_total
                    FROM source_points
                    GROUP BY tenant_id, source_id, metric_type, bucket_start
                )
                INSERT INTO metric_rollups (
                    tenant_id, source_id, metric_type, resolution, bucket_start,
                    value, sample_count, sum_value, min_value, max_value,
                    first_value, last_value, first_timestamp, last_timestamp,
                    metadata, is_provider_total, updated_at
                )
                SELECT
                    points.tenant_id,
                    points.source_id,
                    points.metric_type,
                    :resolution,
                    points.bucket_start,
                    CASE
                        WHEN grouped.has_provider_total THEN
                            sum(points.value) FILTER (WHERE points.is_provider_total)
                        WHEN points.metric_type IN ({sum_keys}) THEN sum(points.value)
                        WHEN points.metric_type IN ({max_keys}) THEN max(points.value)
                        WHEN points.metric_type IN ({last_keys})
                            THEN (array_agg(points.value ORDER BY points.timestamp DESC))[1]
                        ELSE avg(points.value)
                    END,
                    CASE
                        WHEN grouped.has_provider_total
                            THEN count(*) FILTER (WHERE points.is_provider_total)::integer
                        ELSE count(*)::integer
                    END,
                    CASE
                        WHEN grouped.has_provider_total
                            THEN sum(points.value) FILTER (WHERE points.is_provider_total)
                        ELSE sum(points.value)
                    END,
                    CASE
                        WHEN grouped.has_provider_total
                            THEN min(points.value) FILTER (WHERE points.is_provider_total)
                        ELSE min(points.value)
                    END,
                    CASE
                        WHEN grouped.has_provider_total
                            THEN max(points.value) FILTER (WHERE points.is_provider_total)
                        ELSE max(points.value)
                    END,
                    CASE
                        WHEN grouped.has_provider_total
                            THEN (array_agg(points.value ORDER BY points.timestamp ASC)
                                FILTER (WHERE points.is_provider_total))[1]
                        ELSE (array_agg(points.value ORDER BY points.timestamp ASC))[1]
                    END,
                    CASE
                        WHEN grouped.has_provider_total
                            THEN (array_agg(points.value ORDER BY points.timestamp DESC)
                                FILTER (WHERE points.is_provider_total))[1]
                        ELSE (array_agg(points.value ORDER BY points.timestamp DESC))[1]
                    END,
                    CASE
                        WHEN grouped.has_provider_total
                            THEN min(points.timestamp) FILTER (WHERE points.is_provider_total)
                        ELSE min(points.timestamp)
                    END,
                    CASE
                        WHEN grouped.has_provider_total
                            THEN max(points.timestamp) FILTER (WHERE points.is_provider_total)
                        ELSE max(points.timestamp)
                    END,
                    jsonb_build_object(
                        'derived_by', 'backfill',
                        'rollup_resolution', :resolution,
                        'sample_count', CASE
                            WHEN grouped.has_provider_total
                                THEN count(*) FILTER (WHERE points.is_provider_total)
                            ELSE count(*)
                        END,
                        'provider_total', grouped.has_provider_total
                    ),
                    grouped.has_provider_total,
                    now()
                FROM source_points AS points
                JOIN grouped
                  ON grouped.tenant_id = points.tenant_id
                 AND grouped.source_id = points.source_id
                 AND grouped.metric_type = points.metric_type
                 AND grouped.bucket_start = points.bucket_start
                GROUP BY
                    points.tenant_id,
                    points.source_id,
                    points.metric_type,
                    points.bucket_start,
                    grouped.has_provider_total
                ON CONFLICT (
                    tenant_id, source_id, metric_type, resolution, bucket_start
                ) DO UPDATE SET
                    value = EXCLUDED.value,
                    sample_count = EXCLUDED.sample_count,
                    sum_value = EXCLUDED.sum_value,
                    min_value = EXCLUDED.min_value,
                    max_value = EXCLUDED.max_value,
                    first_value = EXCLUDED.first_value,
                    last_value = EXCLUDED.last_value,
                    first_timestamp = EXCLUDED.first_timestamp,
                    last_timestamp = EXCLUDED.last_timestamp,
                    metadata = EXCLUDED.metadata,
                    is_provider_total = EXCLUDED.is_provider_total,
                    updated_at = EXCLUDED.updated_at
                WHERE NOT metric_rollups.is_provider_total
                   OR EXCLUDED.is_provider_total
                """
            )
            await session.execute(query, {"resolution": resolution, "tenant_id": tenant_id})
            await session.commit()


def main() -> None:
    """CLI entry point; this is intentionally never run automatically on startup."""
    parser = argparse.ArgumentParser(description="Rebuild Core metric rollups")
    parser.add_argument("--tenant-id", required=True, help="Workspace UUID to process")
    args = parser.parse_args()
    asyncio.run(rebuild(args.tenant_id))


if __name__ == "__main__":
    main()
