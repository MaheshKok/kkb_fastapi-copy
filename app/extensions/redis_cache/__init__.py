import aioredis

from app.core.config import get_config


config = get_config()
# Note:
# we dont need to use create_pool explicitly as celery does it for us
redis = aioredis.StrictRedis.from_url(
    config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
)
