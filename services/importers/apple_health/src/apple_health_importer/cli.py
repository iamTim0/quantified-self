"""CLI for manual Health Auto Export JSON file ingestion."""

import argparse
import asyncio
import json
import logging
from pathlib import Path

import nats

from apple_health_importer.config import settings
from apple_health_importer.transformer import transform_health_auto_export_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("apple-health-cli")


async def main():
    parser = argparse.ArgumentParser(
        description="Ingest Health Auto Export JSON file into Quantified Self NATS pipeline."
    )
    parser.add_argument(
        "--file", "-f", required=True, help="Path to Health Auto Export JSON file"
    )
    parser.add_argument(
        "--tenant-id", "-t", default=settings.DEFAULT_TENANT_ID, help="Tenant UUID"
    )
    parser.add_argument(
        "--source-id", "-s", default=None, help="Optional source ID"
    )
    parser.add_argument(
        "--nats-url", default=settings.NATS_URL, help="NATS server URL"
    )

    args = parser.parse_args()
    file_path = Path(args.file)

    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:  # noqa: ASYNC230
        try:
            payload = json.load(f)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to parse JSON file {file_path}: {e}")
            return

    source_id = args.source_id or f"apple_health_{args.tenant_id[:8]}"
    events = transform_health_auto_export_json(payload, tenant_id=args.tenant_id, source_id=source_id)

    logger.info(f"Parsed {len(events)} events from {file_path}. Connecting to NATS at {args.nats_url}...")
    nc = await nats.connect(args.nats_url)
    js = nc.jetstream()

    published_count = 0
    for event in events:
        raw_data = json.dumps(event).encode("utf-8")
        await js.publish("qs.ingest.apple_health", raw_data)
        published_count += 1

    logger.info(f"Successfully published {published_count} events to NATS subject 'qs.ingest.apple_health'.")
    await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
