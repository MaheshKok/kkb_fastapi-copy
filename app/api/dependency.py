from aioredis import Redis
from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from httpx import AsyncClient
from httpx import Limits
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.AsyncAngelOne import AsyncAngelOneClient
from app.core.config import Config
from app.database.models import BrokerModel
from app.database.models import CFDStrategyModel
from app.database.models import StrategyModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.broker import BrokerPydanticModel
from app.pydantic_models.enums import BrokerNameEnum
from app.pydantic_models.strategy import CFDStrategyPydanticModel
from app.pydantic_models.strategy import StrategyPydanticModel
from app.pydantic_models.trade import CFDPayloadPydanticModel
from app.pydantic_models.trade import SignalPydanticModel
from app.utils.constants import ANGELONE_BROKER
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


async def get_strategy_pydantic_model(
    signal_pydantic_model: SignalPydanticModel,
    async_redis_client: Redis = Depends(get_async_redis_client),
) -> StrategyPydanticModel:
    redis_strategy_json = await async_redis_client.hget(
        str(signal_pydantic_model.strategy_id), "strategy"
    )
    if not redis_strategy_json:
        async with Database() as async_session:
            fetch_strategy_query = await async_session.execute(
                select(StrategyModel).where(StrategyModel.id == signal_pydantic_model.strategy_id)
            )
            strategy_model = fetch_strategy_query.scalar()
            if not strategy_model:
                raise HTTPException(
                    status_code=404,
                    detail=f"Strategy: {signal_pydantic_model.strategy_id} not found in redis or database",
                )
            redis_set_result = await async_redis_client.hset(
                str(strategy_model.id),
                STRATEGY,
                StrategyPydanticModel.model_validate(strategy_model).model_dump_json(),
            )
            if not redis_set_result:
                raise Exception(f"Redis set strategy: {strategy_model.id} failed")

            return StrategyPydanticModel.model_validate(strategy_model)
    return StrategyPydanticModel.model_validate_json(redis_strategy_json)


async def get_cfd_strategy_pydantic_model(cfd_payload_pydantic_model: CFDPayloadPydanticModel):
    async with Database() as async_session:
        fetch_strategy_query = await async_session.execute(
            select(CFDStrategyModel).where(
                CFDStrategyModel.id == cfd_payload_pydantic_model.strategy_id
            )
        )
        if strategy_model := fetch_strategy_query.scalar():
            return CFDStrategyPydanticModel.model_validate(strategy_model)
        else:
            raise HTTPException(
                status_code=404,
                detail=f"CFD Strategy: {cfd_payload_pydantic_model.strategy_id} not found in database",
            )


async def get_async_httpx_client() -> AsyncClient:
    limits = Limits(max_connections=10, max_keepalive_connections=5)
    client = AsyncClient(http2=True, limits=limits)
    try:
        yield client
    finally:
        await client.aclose()


async def get_broker_pydantic_model(
    config: Config,
    async_redis_client: Redis = Depends(get_async_redis_client),
) -> BrokerPydanticModel:
    broker_id = config.data[ANGELONE_BROKER]["id"]
    broker_json = await async_redis_client.get(broker_id)
    if broker_json:
        broker_pydantic_model: BrokerPydanticModel = BrokerPydanticModel.parse_raw(broker_json)
    else:
        async with Database() as async_session:
            fetch_broker_query = await async_session.execute(
                select(BrokerModel).filter_by(id=str(broker_id))
            )
            broker_model = fetch_broker_query.scalars().one_or_none()

            if not broker_model:
                broker_pydantic_model = BrokerPydanticModel(
                    id=str(broker_id),
                    username=config.data[ANGELONE_BROKER]["username"],
                    password=config.data[ANGELONE_BROKER]["password"],
                    totp=config.data[ANGELONE_BROKER]["totp"],
                    api_key=config.data[ANGELONE_BROKER]["api_key"],
                )
                broker_model = BrokerModel(
                    id=str(broker_id),
                    name=BrokerNameEnum.ANGELONE.value,
                    username=broker_pydantic_model.username,
                    password=broker_pydantic_model.password,
                    totp=broker_pydantic_model.totp,
                    api_key=broker_pydantic_model.api_key,
                )
                await async_session.add(broker_model)
                await async_session.commit()
            else:
                broker_pydantic_model: BrokerPydanticModel = BrokerPydanticModel.model_validate(
                    broker_model
                )

            await async_redis_client.set(broker_id, broker_pydantic_model.model_dump_json())

    return broker_pydantic_model


async def get_angelone_client(
    config: Config = Depends(get_config),
    async_redis_client: Redis = Depends(get_async_redis_client),
) -> AsyncAngelOneClient:
    broker_pydantic_model = await get_broker_pydantic_model(config, async_redis_client)
    async_angelone_client = AsyncAngelOneClient(
        broker_pydantic_model.api_key,
        access_token=broker_pydantic_model.access_token,
        refresh_token=broker_pydantic_model.refresh_token,
        feed_token=broker_pydantic_model.feed_token,
    )
    # async_angelone_client.generateSession(
    #     clientCode=broker_pydantic_model.username,
    #     password=broker_pydantic_model.password,
    #     totp=pyotp.TOTP(broker_pydantic_model.totp).now(),
    # )
    #
    # update_broker_in_redis = False
    # tokens = [
    #     ("refresh_token", async_angelone_client.refresh_token),
    #     ("feed_token", async_angelone_client.feed_token),
    #     ("access_token", async_angelone_client.access_token),
    # ]
    #
    # for token_name, client_token in tokens:
    #     broker_token = getattr(broker_pydantic_model, token_name)
    #     if not broker_token or broker_token != client_token:
    #         setattr(broker_pydantic_model, token_name, client_token)
    #         update_broker_in_redis = True
    #
    # if update_broker_in_redis:
    #     await async_redis_client.set(
    #         str(broker_pydantic_model.id), BrokerSchema.model_validate(broker_pydantic_model).model_dump_json()
    #     )

    return async_angelone_client
