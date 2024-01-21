import asyncio
import json
import logging

from app.api.utils import get_expiry_list_from_alice_blue
from app.core.config import get_config
from app.database.base import get_redis_client


async def sync_expiry_dates_from_alice_blue_to_redis(config):
    result = await get_expiry_list_from_alice_blue()

    async_redis_client = get_redis_client(config)
    for instrument_type, expiry in result.items():
        await async_redis_client.set(instrument_type, json.dumps(expiry))

    logging.info("expiry set from alice blue to redis")


if __name__ == "__main__":
    config = get_config()
    asyncio.run(sync_expiry_dates_from_alice_blue_to_redis(config))
