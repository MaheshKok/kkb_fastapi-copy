from aioredis import Redis
from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import Row
from sqlalchemy import RowMapping
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import StrategyModel
from app.extensions.redis_cache import redis
from app.schemas.trade import TradePostSchema


def get_app(request: Request) -> FastAPI:
    return request.app


async def get_async_session(app: FastAPI = Depends(get_app)) -> AsyncSession:
    async_session = app.state.async_session_maker()
    try:
        async with async_session.begin():
            yield async_session
    finally:
        await async_session.close()


async def is_valid_strategy(
    trade_post_schema: TradePostSchema, db: AsyncSession = Depends(get_async_session)
) -> Row | RowMapping:
    # TODO: Implement in memory caching for strategy_id and symbol
    # query database to check if strategy_id exists
    _query = select(StrategyModel).where(StrategyModel.id == trade_post_schema.strategy_id)
    result = await db.execute(_query)
    strategy_db = result.scalars().one_or_none()

    if not strategy_db:
        raise HTTPException(status_code=400, detail="Invalid strategy_id")
    return strategy_db


async def get_redis_pool() -> Redis:
    try:
        yield redis
    finally:
        await redis.close()
