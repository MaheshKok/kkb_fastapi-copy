import asyncio
from contextlib import asynccontextmanager

import aioredis
from fastapi_sa.database import db
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.core.config import Config
from app.extensions.redis_cache.on_start import cache_ongoing_trades


def get_db_url(config: Config) -> URL:
    config_db = config.data["db"]
    return URL.create(drivername="postgresql+asyncpg", **config_db)


def get_async_session_maker(async_db_url: URL) -> sessionmaker:
    async_engine = create_async_engine(
        async_db_url,
        poolclass=QueuePool,
        pool_recycle=3600,
        pool_pre_ping=True,
        pool_size=60,
        max_overflow=80,
        pool_timeout=30,
    )
    async_session_maker = sessionmaker(
        bind=async_engine, expire_on_commit=False, class_=AsyncSession
    )
    return async_session_maker


def get_redis_client(config: Config) -> aioredis.StrictRedis:
    # Note:
    # we dont need to use create_pool explicitly as celery does it for us
    return aioredis.StrictRedis.from_url(
        config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
    )


@asynccontextmanager
async def lifespan(app):
    async_db_url = get_db_url(app.state.config)
    # app.state.async_session_maker = get_async_session_maker(async_db_url)

    db.init(async_db_url)
    async_redis = get_redis_client(app.state.config)
    app.state.async_redis = async_redis

    # create a task to cache ongoing trades in Redis
    asyncio.create_task(cache_ongoing_trades(async_redis))

    try:
        yield
    finally:
        # Close the connection when the application shuts down
        await app.state.async_redis.close()
        await app.state.async_session_maker.kw["bind"].dispose()
