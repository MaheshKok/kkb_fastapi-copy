from aioredis import Redis
from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from httpx import AsyncClient
from httpx import Limits
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import StrategyModel
from app.database.session_manager.db_session import Database
from app.schemas.strategy import StrategySchema
from app.schemas.trade import CFDPayloadSchema
from app.schemas.trade import SignalPayloadSchema
from app.utils.constants import STRATEGY


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
    redis_strategy_json = await async_redis_client.hget(
        str(signal_payload_schema.strategy_id), "strategy"
    )
    if not redis_strategy_json:
        async with Database() as async_session:
            fetch_strategy_query = await async_session.execute(
                select(StrategyModel).where(StrategyModel.id == signal_payload_schema.strategy_id)
            )
            strategy_model = fetch_strategy_query.scalar()
            if not strategy_model:
                raise HTTPException(
                    status_code=404,
                    detail=f"Strategy: {signal_payload_schema.strategy_id} not found in redis or database",
                )
            redis_set_result = await async_redis_client.hset(
                str(strategy_model.id),
                STRATEGY,
                StrategySchema.model_validate(strategy_model).model_dump_json(),
            )
            if not redis_set_result:
                raise Exception(f"Redis set strategy: {strategy_model.id} failed")

            return StrategySchema.model_validate(strategy_model)
    return StrategySchema.model_validate_json(redis_strategy_json)


async def get_cfd_strategy_schema(cfd_payload_schema: CFDPayloadSchema):
    async with Database() as async_session:
        fetch_strategy_query = await async_session.execute(
            select(StrategyModel).where(StrategyModel.id == cfd_payload_schema.strategy_id)
        )
        strategy_model = fetch_strategy_query.scalar()
        if not strategy_model:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy: {cfd_payload_schema.strategy_id} not found in database",
            )
        return StrategySchema.model_validate(strategy_model)


async def get_async_httpx_client() -> AsyncClient:
    limits = Limits(max_connections=10, max_keepalive_connections=5)
    client = AsyncClient(http2=True, limits=limits)
    try:
        yield client
    finally:
        await client.aclose()
