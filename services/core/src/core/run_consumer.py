"""Standalone worker script to start NATS JetStream consumer and ingest pending events into PostgreSQL TimescaleDB."""

import asyncio
import logging
from core.events.consumer import start_consumer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

async def main():
    logger.info("Starting Core Data Service JetStream consumer...")
    nc = await start_consumer()
    logger.info("Consumer active. Ingesting pending NATS messages...")
    
    # Process for 5 seconds to ingest queued batch
    await asyncio.sleep(5)
    await nc.close()
    logger.info("Batch ingestion cycle complete.")

if __name__ == "__main__":
    asyncio.run(main())
