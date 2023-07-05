import aioredis
from aioredis import Redis

from app.core.config import get_config


async def get_async_redis_client(config_file) -> Redis:
    config = get_config(config_file)
    async_redis_client = await aioredis.StrictRedis.from_url(
        config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
    )
    return async_redis_client
