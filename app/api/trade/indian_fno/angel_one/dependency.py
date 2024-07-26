import logging

import pyotp
from aioredis import Redis
from fastapi import Depends
from sqlalchemy import select

from app.api.dependency import get_async_redis_client
from app.api.dependency import get_strategy_pyd_model
from app.api.trade.indian_fno.angel_one.db_operations import get_order_pyd_model
from app.broker_clients.async_angel_one import AsyncAngelOneClient
from app.database.schemas import BrokerDBModel
from app.database.schemas import StrategyDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.angel_one import InitialOrderPydModel
from app.pydantic_models.broker import BrokerPydModel
from app.pydantic_models.strategy import StrategyPydModel


async def get_strategy_pyd_model_from_order(
    initial_order_pyd_model: InitialOrderPydModel = Depends(get_order_pyd_model),
) -> StrategyPydModel:
    async with Database() as async_session:
        fetch_strategy_query = await async_session.execute(
            select(StrategyDBModel).filter_by(id=initial_order_pyd_model.strategy_id)
        )
        strategy_db_model = fetch_strategy_query.scalars().one()
        if not strategy_db_model:
            raise Exception(f"Strategy: [ {initial_order_pyd_model.instrument} ] not found in DB")
        return StrategyPydModel.model_validate(strategy_db_model)


async def get_async_angelone_client(
    async_redis_client: Redis = Depends(get_async_redis_client),
    strategy_pyd_model: StrategyPydModel = Depends(get_strategy_pyd_model),
) -> AsyncAngelOneClient:
    broker_id = str(strategy_pyd_model.broker_id)
    broker_json = await async_redis_client.get(broker_id)
    if broker_json:
        broker_pyd_model: BrokerPydModel = BrokerPydModel.parse_raw(broker_json)
    else:
        async with Database() as async_session:
            fetch_broker_query = await async_session.execute(
                select(BrokerDBModel).filter_by(id=str(broker_id))
            )
            broker_db_model = fetch_broker_query.scalars().one()
            broker_pyd_model: BrokerPydModel = BrokerPydModel.model_validate(broker_db_model)
            if not (
                broker_pyd_model.access_token
                and broker_pyd_model.refresh_token
                and broker_pyd_model.feed_token
            ):
                client = AsyncAngelOneClient(broker_pyd_model.api_key)
                await client.generate_session(
                    client_code=broker_pyd_model.username,
                    password=broker_pyd_model.password,
                    totp=pyotp.TOTP(broker_pyd_model.totp).now(),
                )
                broker_db_model.access_token = client.access_token

            await async_session.commit()
            broker_pyd_model.access_token = client.access_token
            broker_pyd_model.refresh_token = client.refresh_token
            broker_pyd_model.feed_token = client.feed_token
            # update redis cache with new session_id
            await async_redis_client.set(
                str(broker_pyd_model.id), broker_pyd_model.model_dump_json()
            )
            logging.info(
                f"successfully updated session token for: [ {broker_db_model.name} ] user: [ {broker_db_model.username} ] in db and redis"
            )

    async_angelone_client = AsyncAngelOneClient(
        broker_pyd_model.api_key,
        access_token=broker_pyd_model.access_token,
        refresh_token=broker_pyd_model.refresh_token,
        feed_token=broker_pyd_model.feed_token,
    )
    return async_angelone_client
