from aioredis import Redis
from fastapi import Depends
from fastapi import FastAPI
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.trade import EntryTradeSchema


def get_app(request: Request) -> FastAPI:
    return request.app


async def get_async_session(app: FastAPI = Depends(get_app)) -> AsyncSession:
    async_session = app.state.async_session_maker()
    yield async_session


async def get_async_redis(app: FastAPI = Depends(get_app)) -> Redis:
    yield app.state.async_redis


async def is_valid_strategy(
    trade_post_schema: EntryTradeSchema, async_redis: Redis = Depends(get_async_redis)
):
    # TODO: check redis cache if strategy_id exists
    # its working, 1 sec 10 trades, now change celery redis to memtera or something else
    # as upstash is cancelling or some other reason
    # strategy_list = await async_redis.lrange("strategy_list", 0, -1)
    # if trade_post_schema.strategy_id not in strategy_list:
    #     raise HTTPException(status_code=400, detail="Invalid strategy_id")
    return True
