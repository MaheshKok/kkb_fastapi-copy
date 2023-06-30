from aioredis import Redis
from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.strategy import StrategySchema
from app.schemas.trade import SignalPayloadSchema


def get_app(request: Request) -> FastAPI:
    return request.app


async def get_async_session(app: FastAPI = Depends(get_app)) -> AsyncSession:
    async_session = app.state.async_session_maker()
    yield async_session


async def get_async_redis_client(app: FastAPI = Depends(get_app)) -> Redis:
    yield app.state.async_redis_client


async def get_strategy_schema(
    signal_payload_schema: SignalPayloadSchema,
    async_redis_client: Redis = Depends(get_async_redis_client),
) -> StrategySchema:
    redis_strategy_json = await async_redis_client.get(str(signal_payload_schema.strategy_id))
    if not redis_strategy_json:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy: {signal_payload_schema.strategy_id} not found in redis",
        )
    return StrategySchema.parse_raw(redis_strategy_json)


async def get_async_httpx_client() -> AsyncClient:
    async with AsyncClient() as client:
        yield client
