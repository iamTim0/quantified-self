import asyncio
import json
import logging
import nats
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from oura_importer.config import settings
from oura_importer.client import OuraClient
from oura_importer.transformer import transform_sleep_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fetch_and_publish(nc):
    try:
        client = OuraClient()
        sleep_data = await client.get_sleep()
        
        data_points = transform_sleep_data(sleep_data)
        
        js = nc.jetstream()
        for dp in data_points:
            await js.publish("qs.ingest.oura", json.dumps(dp).encode())
            logger.info(f"Published data point: {dp.get('idempotency_key')}")
            
    except Exception as e:
        logger.error(f"Error fetching/publishing data: {e}")

async def main():
    nc = await nats.connect(settings.NATS_URL)
    logger.info("Connected to NATS")
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        fetch_and_publish, 
        'interval', 
        seconds=settings.POLL_INTERVAL_SECONDS, 
        args=[nc]
    )
    scheduler.start()
    logger.info(f"Started scheduler, polling every {settings.POLL_INTERVAL_SECONDS} seconds")
    
    # Run fetch immediately once
    await fetch_and_publish(nc)
    
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await nc.close()

if __name__ == "__main__":
    asyncio.run(main())
