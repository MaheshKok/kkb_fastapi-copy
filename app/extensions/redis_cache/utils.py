import aioredis

from app.core.config import get_config


async def get_async_redis(config_file) -> aioredis.StrictRedis:
    config = get_config(config_file)
    async_redis = await aioredis.StrictRedis.from_url(
        config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
    )
    return async_redis
