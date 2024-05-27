import asyncio
import logging

import httpx
import pyotp
from aioredis import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.trade.indian_fno.alice_blue.utils import get_pya3_obj
from app.api.trade.indian_fno.alice_blue.utils import update_ablue_session_token
from app.broker_clients.async_angel_one import AsyncAngelOneClient
from app.core.config import get_config
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.database.schemas import BrokerDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.broker import BrokerPydModel
from app.pydantic_models.enums import BrokerNameEnum


logging.basicConfig(level=logging.DEBUG)


async def get_angel_one_access_token():
    pass


# refactored update and logging into a separate coroutine
async def task_update_ablue_session_token(async_session, async_redis_client):
    try:
        # get broker_clients model from db filtered by username
        fetch_broker_query = await async_session.execute(
            select(BrokerDBModel).filter_by(name=BrokerNameEnum.ALICEBLUE.value)
        )
        broker_db_models = fetch_broker_query.scalars().all()

        async with httpx.AsyncClient() as httpx_client:
            tasks = []
            for broker_db_model in broker_db_models:
                if broker_db_model.username != "921977":
                    continue

                # fetch pya3 object
                pya3_obj = await get_pya3_obj(
                    async_redis_client, str(broker_db_model.id), httpx_client
                )

                # create a Task for each update operation
                task = asyncio.create_task(
                    update_ablue_session_token(
                        pya3_obj=pya3_obj, async_redis_client=async_redis_client
                    )
                )
                tasks.append(task)

            # wait for all tasks to complete
            await asyncio.gather(*tasks)

        logging.info(
            f"successfully updated session token for: [ {broker_db_model.name} ] user: [ {broker_db_model.username} ] in db and redis"
        )
    except Exception as e:
        logging.error(
            f"Error while updating session token for: [ {broker_db_model.name} ] user: [ {broker_db_model.username} ], {e}"
        )


async def task_update_angelone_session_token(
    async_redis_client: Redis, async_session: AsyncSession
):
    fetch_broker_query = await async_session.execute(
        select(BrokerDBModel).filter_by(name=BrokerNameEnum.ANGELONE.value)
    )
    broker_db_models = fetch_broker_query.scalars().all()
    for broker_db_model in broker_db_models:
        broker_pyd_model = BrokerPydModel.model_validate(broker_db_model)
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
        await async_redis_client.set(str(broker_db_model.id), broker_pyd_model.model_dump_json())
        logging.info(
            f"successfully updated session token for: [ {broker_db_model.name} ] user: [ {broker_db_model.username} ] in db and redis"
        )


async def cron_update_session_token():
    config = get_config()
    async_redis_client = await get_redis_client(config)

    Database.init(get_db_url(config))

    async with Database() as async_session:
        await task_update_ablue_session_token(
            async_session=async_session,
            async_redis_client=async_redis_client,
        )
        await task_update_angelone_session_token(
            async_session=async_session,
            async_redis_client=async_redis_client,
        )


if __name__ == "__main__":
    asyncio.run(cron_update_session_token())
