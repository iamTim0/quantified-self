"""Yazio Importer Main Service Entry Point.

Orchestrates task-driven polling of Yazio API, transforms raw consumed items into standard
DataPoints with SHA256 idempotency_keys, and publishes to NATS subject 'qs.ingest.yazio'.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import httpx
import nats

from yazio_importer.client import (
    YazioApiError,
    YazioClient,
    YazioRateLimitError,
    YazioUnauthorizedError,
)
from yazio_importer.config import settings
from yazio_importer.transformer import transform_consumed_items


def _get_log_dir() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "logs").is_dir() or ((parent / "pyproject.toml").exists() and parent.name == "quantified-self"):
            log_dir = parent / "logs"
            log_dir.mkdir(exist_ok=True)
            return log_dir
    log_dir = Path.cwd() / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir


def _setup_importer_logging():
    """Configure rotating file log handlers for the Yazio importer service."""
    _log_dir = _get_log_dir()

    log_format = "%(asctime)s [qs-importer-yazio] [%(levelname)s] %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(formatter)

    service_handler = RotatingFileHandler(
        _log_dir / "qs-importer-yazio.log", maxBytes=10 * 1024 * 1024, backupCount=5
    )
    service_handler.setFormatter(formatter)

    platform_handler = RotatingFileHandler(
        _log_dir / "qs-platform.log", maxBytes=10 * 1024 * 1024, backupCount=5
    )
    platform_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [stdout_handler, service_handler, platform_handler]
    root.setLevel(logging.INFO)


_setup_importer_logging()
logger = logging.getLogger(__name__)

active_syncs: set[str] = set()


import uuid


async def get_connector_token_from_core(
    tenant_id: str, req_id: str = "req_importer_poll"
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Fetch decrypted access token & source_id for Yazio connector from Core Data Service DB."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/yazio/token"
    headers = {"X-Tenant-ID": tenant_id, "X-Request-ID": req_id}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "active" and data.get("access_token"):
                    source_id = data.get("source_id") or str(
                        uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant_id}:yazio")
                    )
                    return data["access_token"], source_id, data.get("config", {})
            return None, None, None
        except Exception as e:
            logger.warning(f"Could not reach Core Data Service to fetch connector token: {e}")
            return None, None, None


product_cache: dict[str, str] = {}
recipe_cache: dict[str, str] = {}


async def resolve_product_name(client: YazioClient, product_id: str) -> str:
    if product_id in product_cache:
        return product_cache[product_id]
    try:
        p = await client.get_product(product_id)
        if isinstance(p, dict):
            brand = p.get("brand") or p.get("brand_name")
            name = p.get("name") or p.get("title") or p.get("product_name")
            if brand and name:
                full_name = f"{brand} - {name}"
            else:
                full_name = name or brand or f"Produkt #{product_id[:8]}"
            product_cache[product_id] = full_name
            return full_name
    except Exception as e:
        logger.debug(f"Could not fetch name for product {product_id}: {e}")
    fallback = f"Produkt #{product_id[:8]}"
    product_cache[product_id] = fallback
    return fallback


async def resolve_recipe_name(client: YazioClient, recipe_id: str) -> str:
    if recipe_id in recipe_cache:
        return recipe_cache[recipe_id]
    try:
        r = await client.get_recipe(recipe_id)
        if isinstance(r, dict):
            name = r.get("name") or r.get("title") or f"Rezept #{recipe_id[:8]}"
            recipe_cache[recipe_id] = name
            return name
    except Exception as e:
        logger.debug(f"Could not fetch name for recipe {recipe_id}: {e}")
    fallback = f"Rezept #{recipe_id[:8]}"
    recipe_cache[recipe_id] = fallback
    return fallback


async def fetch_and_publish(
    nc: nats.NATS, tenant_id: str, source_id: str, token: str, lookback_days: int
):
    """Poll Yazio API for diary consumed items and publish to NATS."""
    logger.info(f"Polling Yazio API v15 for diary metrics (tenant={tenant_id})...")
    client = YazioClient(access_token=token)
    js = nc.jetstream()

    daily_responses = []
    now = datetime.now(timezone.utc)

    for d in range(lookback_days + 1):
        day_str = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        try:
            items_data = await client.get_consumed_items(date=day_str)
            if items_data:
                daily_responses.append((day_str, items_data))
        except YazioUnauthorizedError:
            logger.error(
                f"Yazio API 401 Unauthorized for tenant {tenant_id}. "
                "The stored access token is invalid or expired. "
                "Please re-enter credentials or Bearer Token in Dashboard UI."
            )
            break
        except (YazioRateLimitError, YazioApiError) as e:
            logger.error(f"Failed to fetch Yazio consumed items for {day_str}: {e}")

    # Collect unique product_ids and recipe_ids to resolve food names
    product_ids_to_resolve = set()
    recipe_ids_to_resolve = set()

    for _, resp in daily_responses:
        if isinstance(resp, dict):
            for p in resp.get("products") or []:
                if isinstance(p, dict) and p.get("product_id"):
                    pid = str(p["product_id"])
                    if pid not in product_cache:
                        product_ids_to_resolve.add(pid)
            for r in resp.get("recipe_portions") or []:
                if isinstance(r, dict) and r.get("recipe_id"):
                    rid = str(r["recipe_id"])
                    if rid not in recipe_cache:
                        recipe_ids_to_resolve.add(rid)

    # Resolve product and recipe names
    for pid in product_ids_to_resolve:
        await resolve_product_name(client, pid)

    for rid in recipe_ids_to_resolve:
        await resolve_recipe_name(client, rid)

    # Transform into DataPoints
    data_points = []
    for day_str, items_data in daily_responses:
        dps = transform_consumed_items(
            raw_data=items_data,
            day=day_str,
            tenant_id=tenant_id,
            source_id=source_id,
            product_cache=product_cache,
            recipe_cache=recipe_cache,
        )
        data_points.extend(dps)

    published_count = 0
    for dp in data_points:
        payload = json.dumps(dp).encode("utf-8")
        await js.publish("qs.ingest.yazio", payload)
        published_count += 1

    logger.info(
        f"Successfully published {published_count} data points to NATS subject 'qs.ingest.yazio'."
    )


async def process_task_message(msg, nc: nats.NATS):
    try:
        payload = json.loads(msg.data.decode("utf-8"))
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            logger.warning("Missing tenant_id in task payload")
            await msg.ack()
            return

        if tenant_id in active_syncs:
            logger.info("Sync already in progress for tenant, skipping duplicate task")
            await msg.ack()
            return

        active_syncs.add(tenant_id)
        try:
            token, source_id, config = await get_connector_token_from_core(tenant_id)
            if not token or not source_id:
                logger.info(
                    f"No active Yazio connector configured in Dashboard UI for tenant '{tenant_id}'. "
                    "Waiting for token configuration via Dashboard UI..."
                )
                return

            config = config or {}
            lookback_days = config.get("lookback_days", settings.POLL_LOOKBACK_DAYS)
            await fetch_and_publish(nc, tenant_id, source_id, token, lookback_days)
        finally:
            active_syncs.discard(tenant_id)
            await msg.ack()
    except Exception as e:
        logger.error(f"Error processing task message: {e}")


async def main():
    logger.info(f"Starting Yazio Importer Service (tenant={settings.TENANT_ID})...")
    nc = await nats.connect(settings.NATS_URL)
    logger.info(f"Connected to NATS at {settings.NATS_URL}")

    js = nc.jetstream()
    try:
        await js.add_stream(name="tasks", subjects=["qs.task.sync.>"])
    except Exception as e:
        logger.info(f"Stream 'tasks' check: {e}")

    await js.subscribe(
        "qs.task.sync.yazio",
        queue="yazio_importer_task_group",
        cb=lambda msg: process_task_message(msg, nc),
    )
    logger.info(
        "Subscribed to NATS subject 'qs.task.sync.yazio' (queue group: 'yazio_importer_task_group')"
    )

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping Yazio Importer Service...")
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
