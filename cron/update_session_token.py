import asyncio
import logging

import httpx
from sqlalchemy import select

from app.api.utils import update_session_token
from app.broker.utils import get_pya3_obj
from app.core.config import get_config
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.database.models import BrokerModel
from app.database.session_manager.db_session import Database


logging.basicConfig(level=logging.DEBUG)


# refactored update and logging into a separate coroutine
async def update_session_token_with_logging(pya3_obj, async_redis_client, broker_model):
    try:
        await update_session_token(pya3_obj=pya3_obj, async_redis_client=async_redis_client)
        logging.info(
            f"successfully updated session token for: [ {broker_model.name} ] user: [ {broker_model.username} ]"
        )
    except Exception as e:
        logging.error(
            f"Error while updating session token for: [ {broker_model.name} ] user: [ {broker_model.username} ], {e}"
        )


async def task_update_session_token():
    config = get_config()
    async_redis_client = await get_redis_client(config)

    Database.init(get_db_url(config))

    async with Database() as async_session:
        # get broker model from db filtered by username
        fetch_broker_query = await async_session.execute(
            select(BrokerModel).filter_by(name="ALICEBLUE")
        )
        broker_models = fetch_broker_query.scalars().all()

        async with httpx.AsyncClient() as httpx_client:
            tasks = []
            for broker_model in broker_models:
                pya3_obj = await get_pya3_obj(
                    async_redis_client, str(broker_model.id), httpx_client
                )

                # create a Task for each update operation
                task = asyncio.create_task(
                    update_session_token_with_logging(pya3_obj, async_redis_client, broker_model)
                )
                tasks.append(task)

            # wait for all tasks to complete
            await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(task_update_session_token())
