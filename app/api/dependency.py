import pyotp
from aioredis import Redis
from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from httpx import AsyncClient
from httpx import Limits
from SmartApi import SmartConnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Config
from app.database.models import BrokerModel
from app.database.models import CFDStrategyModel
from app.database.models import StrategyModel
from app.database.session_manager.db_session import Database
from app.schemas.broker import BrokerSchema
from app.schemas.strategy import CFDStrategySchema
from app.schemas.strategy import StrategySchema
from app.schemas.trade import CFDPayloadSchema
from app.schemas.trade import SignalPayloadSchema
from app.utils.constants import ANGELONE_BROKER_ID
from app.utils.constants import STRATEGY


def get_app(request: Request) -> FastAPI:
    return request.app


async def get_config(app: FastAPI = Depends(get_app)):
    yield app.state.config


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
            select(CFDStrategyModel).where(CFDStrategyModel.id == cfd_payload_schema.strategy_id)
        )
        if strategy_model := fetch_strategy_query.scalar():
            return CFDStrategySchema.model_validate(strategy_model)
        else:
            raise HTTPException(
                status_code=404,
                detail=f"CFD Strategy: {cfd_payload_schema.strategy_id} not found in database",
            )


async def get_async_httpx_client() -> AsyncClient:
    limits = Limits(max_connections=10, max_keepalive_connections=5)
    client = AsyncClient(http2=True, limits=limits)
    try:
        yield client
    finally:
        await client.aclose()


async def get_broker_schema(
    async_redis_client: Redis = Depends(get_async_redis_client),
    broker_id: str = ANGELONE_BROKER_ID,
) -> BrokerSchema:
    broker_json = await async_redis_client.get(broker_id)
    if broker_json:
        broker_schema: BrokerSchema = BrokerSchema.parse_raw(broker_json)
    else:
        async with Database() as async_session:
            fetch_broker_query = await async_session.execute(
                select(BrokerModel).filter_by(id=str(broker_id))
            )
            broker_model = fetch_broker_query.scalars().one_or_none()

            if not broker_model:
                raise HTTPException(
                    status_code=404, detail=f"Angel One Broker: {broker_id} not found"
                )
            broker_schema: BrokerSchema = BrokerSchema.model_validate(broker_model)
            await async_redis_client.set(broker_id, broker_schema.model_dump_json())

    return broker_schema


async def get_smart_connect_client(
    config: Config = Depends(get_config),
    async_redis_client: Redis = Depends(get_async_redis_client),
) -> SmartConnect:
    broker_id = config.data[ANGELONE_BROKER_ID]
    broker_schema = await get_broker_schema(async_redis_client, broker_id)
    client = SmartConnect(broker_schema.api_key)
    client.generateSession(
        clientCode=broker_schema.username,
        password=broker_schema.password,
        totp=pyotp.TOTP(broker_schema.totp).now(),
    )
    return client
