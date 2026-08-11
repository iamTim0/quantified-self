"""CLI for manual Streak 2.0 JSON export file ingestion."""

import argparse
import asyncio
import json
import logging
from pathlib import Path

import nats

from streak_importer.config import settings
from streak_importer.transformer import transform_streak_export_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("streak-cli")


async def main():
    parser = argparse.ArgumentParser(
        description="Ingest Streak 2.0 JSON export file into Quantified Self NATS pipeline."
    )
    parser.add_argument(
        "--file", "-f", required=True, help="Path to Streak 2.0 JSON export file"
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

    try:
        raw_payload = await asyncio.to_thread(file_path.read_text, encoding="utf-8")
        payload = json.loads(raw_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.error(
            "Failed to parse JSON file %s (%s)", file_path, type(exc).__name__
        )
        return

    source_id = args.source_id or f"streak_{args.tenant_id[:8]}"
    events = transform_streak_export_json(payload, tenant_id=args.tenant_id, source_id=source_id)

    logger.info("Parsed %d events from %s. Connecting to NATS...", len(events), file_path)
    nc = await nats.connect(args.nats_url)
    js = nc.jetstream()

    published_count = 0
    for event in events:
        raw_data = json.dumps(event).encode("utf-8")
        await js.publish("qs.ingest.streak", raw_data)
        published_count += 1

    logger.info(f"Successfully published {published_count} events to NATS subject 'qs.ingest.streak'.")
    await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
