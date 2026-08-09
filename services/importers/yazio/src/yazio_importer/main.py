"""Yazio Importer Main Service Entry Point.

Orchestrates task-driven polling of Yazio API, transforms raw consumed items into standard
DataPoints with SHA256 idempotency_keys, and publishes to NATS subject 'qs.ingest.yazio'.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
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
from yazio_importer.internal_auth import internal_headers
from yazio_importer.sync_task import SyncTask, parse_sync_task, resolve_window
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


async def report_sync_result_to_core(
    task: SyncTask,
    *,
    status: str,
    message: str,
    points_received: int | None = None,
):
    """Close out the sync run in Core.

    Only a run Core sees reach success moves the adaptive-window resume point
    forward, so reporting the outcome is what keeps the next window correct.
    """
    url = (
        f"{settings.CORE_SERVICE_URL}"
        f"/api/v1/internal/data/sources/{task.source_id or task.source_type}/status"
    )
    headers = internal_headers(task.request_id, task.tenant_id)
    payload: dict[str, Any] = {
        "sync_status": status,
        "last_sync_message": message,
        "sync_run_id": task.sync_run_id,
    }
    if points_received is not None:
        payload["points_received"] = points_received

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(url, headers=headers, json=payload)
        except Exception as e:
            logger.warning(f"Could not report sync result to Core: {e}")


async def get_connector_token_from_core(
    tenant_id: str,
    req_id: str = "req_importer_poll",
    source_ref: str | None = None,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Fetch decrypted access token & source_id for Yazio connector from Core Data Service DB."""
    # Addressed by connector id when the sync task carries one: a tenant may
    # hold several connectors of this type, and the bare type would hand back
    # an arbitrary one of them.
    reference = source_ref or "yazio"
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{reference}/token"
    headers = internal_headers(req_id, tenant_id)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "active" and data.get("access_token"):
                    # No synthetic fallback. It used to be
                    # `uuid5(NAMESPACE_DNS, f"{tenant_id}:<type>")`, which collapsed
                    # every instance of a type onto one id -- and that id is the
                    # second component of every idempotency key, so two connectors
                    # would have written into a single indistinguishable series.
                    source_id = data.get("source_id")
                    if not source_id:
                        logger.warning(
                            "Core returned no source_id for tenant %s; refusing to guess one.",
                            tenant_id,
                        )
                        return None, None, None
                    return data["access_token"], source_id, data.get("config", {})
            return None, None, None
        except Exception as e:
            logger.warning(f"Could not reach Core Data Service to fetch connector token: {e}")
            return None, None, None


product_cache: dict[str, dict[str, Any]] = {}
recipe_cache: dict[str, dict[str, Any]] = {}


async def resolve_product_info(client: YazioClient, product_id: str) -> dict[str, Any]:
    if product_id in product_cache:
        return product_cache[product_id]
    try:
        p = await client.get_product(product_id)
        if isinstance(p, dict) and p:
            brand = p.get("brand") or p.get("brand_name")
            name = p.get("name") or p.get("title") or p.get("product_name")
            if brand and name:
                full_name = f"{brand} - {name}"
            else:
                full_name = name or brand or f"Produkt #{product_id[:8]}"

            nutrients = p.get("nutrients") or {}
            base_unit = str(p.get("base_unit") or p.get("base") or p.get("unit") or "100g").lower()
            raw_base_amt = p.get("base_amount")

            if raw_base_amt is not None and float(raw_base_amt) > 0:
                base_amount = float(raw_base_amt)
            elif "100" in base_unit:
                base_amount = 100.0
            elif "1g" in base_unit or "1ml" in base_unit or base_unit in ("g", "ml"):
                base_amount = 1.0
            elif "serving" in base_unit or "portion" in base_unit or "piece" in base_unit:
                base_amount = 1.0
            else:
                base_amount = 100.0

            info = {
                "name": full_name,
                "base_amount": base_amount,
                "base_unit": base_unit,
                "energy_kcal": float(nutrients.get("energy.energy") or p.get("calories") or p.get("energy") or 0.0),
                "protein_g": float(nutrients.get("nutrient.protein") or p.get("protein") or 0.0),
                "carbs_g": float(nutrients.get("nutrient.carb") or p.get("carbs") or 0.0),
                "fat_g": float(nutrients.get("nutrient.fat") or p.get("fat") or 0.0),
            }
            product_cache[product_id] = info
            return info
    except Exception as e:
        logger.debug(f"Could not fetch info for product {product_id}: {e}")

    fallback = {
        "name": f"Produkt #{product_id[:8]}",
        "base_amount": 100.0,
        "energy_kcal": 0.0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
    }
    product_cache[product_id] = fallback
    return fallback


async def resolve_recipe_name(client: YazioClient, recipe_id: str) -> str:
    if recipe_id in recipe_cache:
        return recipe_cache[recipe_id]["name"]
    try:
        r = await client.get_recipe(recipe_id)
        if isinstance(r, dict) and r:
            name = r.get("name") or r.get("title") or f"Rezept #{recipe_id[:8]}"
            recipe_cache[recipe_id] = {"name": name}
            return name
    except Exception as e:
        logger.debug(f"Could not fetch name for recipe {recipe_id}: {e}")
    fallback = f"Rezept #{recipe_id[:8]}"
    recipe_cache[recipe_id] = {"name": fallback}
    return fallback


def days_in_window(start: datetime, end: datetime) -> list[str]:
    """The calendar days a window touches, as ``YYYY-MM-DD``.

    Yazio's diary API is day-addressed, so a window has to be expanded into the
    days it covers. Narrower windows therefore mean directly fewer HTTP calls:
    a two-hour incremental window is one or two days instead of the previous
    unconditional 31.
    """
    first = start.date()
    last = end.date()
    span = (last - first).days
    return [(first + timedelta(days=offset)).isoformat() for offset in range(span + 1)]


async def fetch_and_publish(
    nc: nats.NATS, task: SyncTask, source_id: str, token: str, config: dict[str, Any]
):
    """Poll the Yazio diary over the window Core chose and publish to NATS."""
    tenant_id = task.tenant_id
    window_start, window_end = resolve_window(task, config)
    day_strings = days_in_window(window_start, window_end)

    logger.info(
        "[req_id=%s] Polling Yazio for tenant=%s over %d day(s) (%s..%s) mode=%s",
        task.request_id,
        tenant_id,
        len(day_strings),
        window_start.date().isoformat(),
        window_end.date().isoformat(),
        task.mode,
    )

    client = YazioClient(access_token=token)
    js = nc.jetstream()

    daily_responses = []

    for day_str in day_strings:
        try:
            items_data = await client.get_consumed_items(date=day_str)
            summary_data = await client.get_daily_summary(date=day_str)
            if items_data and isinstance(items_data, dict):
                if summary_data and isinstance(summary_data, dict):
                    items_data["summary"] = summary_data.get("summary") or summary_data.get("totals") or summary_data
                daily_responses.append((day_str, items_data))
        except YazioUnauthorizedError:
            err_msg = "HTTP 401 Unauthorized: Stored Yazio token is invalid or expired."
            logger.error("[req_id=%s] Yazio API 401 for tenant %s.", task.request_id, tenant_id)
            await report_sync_result_to_core(task, status="error", message=err_msg)
            return
        except (YazioRateLimitError, YazioApiError) as e:
            logger.error(
                "[req_id=%s] Failed to fetch Yazio items for %s: %s",
                task.request_id,
                day_str,
                e,
            )

    # Collect unique product_ids and recipe_ids to resolve food names and nutrients
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

    # Resolve product and recipe names & nutrients
    for pid in product_ids_to_resolve:
        await resolve_product_info(client, pid)

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
        dp["request_id"] = task.request_id
        if task.sync_run_id:
            dp["sync_run_id"] = task.sync_run_id
        await js.publish("qs.ingest.yazio", json.dumps(dp).encode("utf-8"))
        published_count += 1

    logger.info(
        "[req_id=%s] Published %d data points to 'qs.ingest.yazio'.",
        task.request_id,
        published_count,
    )
    await report_sync_result_to_core(
        task,
        status="idle",
        message=f"{published_count} data point(s) published from Yazio.",
        points_received=published_count,
    )


async def process_task_message(msg, nc: nats.NATS):
    try:
        task = parse_sync_task(json.loads(msg.data.decode("utf-8")))
        if task is None:
            logger.warning("Missing tenant_id in task payload; dropping.")
            await msg.ack()
            return

        tenant_id = task.tenant_id
        # Keyed on the connector instance, not the tenant. Keyed on the tenant,
        # a user's second connector of this type had its task discarded as a
        # "duplicate" whenever the first was still running.
        lock_key = f"{tenant_id}:{task.source_id or task.source_type}"
        if lock_key in active_syncs:
            logger.info("Sync already in progress for tenant, skipping duplicate task")
            await msg.ack()
            return

        active_syncs.add(lock_key)
        try:
            token, source_id, config = await get_connector_token_from_core(
                tenant_id, req_id=task.request_id, source_ref=task.source_id
            )
            if not token or not source_id:
                logger.info(
                    f"No active Yazio connector configured in Dashboard UI for tenant '{tenant_id}'. "
                    "Waiting for token configuration via Dashboard UI..."
                )
                return

            await fetch_and_publish(nc, task, source_id, token, config or {})
        finally:
            active_syncs.discard(lock_key)
            await msg.ack()
    except Exception as e:
        logger.error(f"Error processing task message: {e}")


async def main():
    logger.info("Starting Yazio Importer Service; awaiting sync tasks on NATS...")
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
