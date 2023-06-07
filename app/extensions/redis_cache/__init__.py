import aioredis
from aioredis import Redis

from app.core.config import get_config


async def get_redis_pool() -> Redis:
    config = get_config()
    redis = aioredis.StrictRedis.from_url(
        config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
    )
    try:
        yield redis
    finally:
        await redis.close()
