import logging
from datetime import datetime

from aioredis import Redis
from sqlalchemy import select

from app.database.models import BrokerModel
from app.database.sqlalchemy_client.client import Database
from app.schemas.broker import BrokerSchema
from app.services.broker.alice_blue import Pya3Aliceblue
from app.utils.constants import EDELWEISS_DATE_FORMAT
from app.utils.in_memory_cache import current_and_next_expiry_cache


async def get_expiry_list(async_redis_client):
    expiry_list = eval(await async_redis_client.get("expiry_list"))
    return [datetime.strptime(expiry, EDELWEISS_DATE_FORMAT).date() for expiry in expiry_list]


async def get_current_and_next_expiry(async_redis_client, todays_date):
    if todays_date in current_and_next_expiry_cache:
        return current_and_next_expiry_cache[todays_date]

    is_today_expiry = False
    current_expiry_date = None
    next_expiry_date = None
    expiry_list = await get_expiry_list(async_redis_client)
    for index, expiry_date in enumerate(expiry_list):
        if todays_date > expiry_date:
            continue
        elif expiry_date == todays_date:
            next_expiry_date = expiry_list[index + 1]
            current_expiry_date = expiry_date
            is_today_expiry = True
            break
        elif todays_date < expiry_date:
            current_expiry_date = expiry_date
            break

    current_and_next_expiry_cache[todays_date] = (
        current_expiry_date,
        next_expiry_date,
        is_today_expiry,
    )

    return current_expiry_date, next_expiry_date, is_today_expiry


async def refresh_and_get_session_id(pya3_obj: Pya3Aliceblue, async_redis_client: Redis):
    session_id = await pya3_obj.login_and_get_session_id()

    async with Database():
        # get broker model from db filtered by username
        fetch_broker_query = await Database.session.execute(
            select(BrokerModel).where(BrokerModel.username == pya3_obj.user_id)
        )
        broker_model = fetch_broker_query.scalars().one_or_none()
        broker_model.access_token = session_id
        await Database.session.flush()

        # update redis cache with new session_id
        redis_set_result = await async_redis_client.set(
            str(broker_model.id), BrokerSchema.from_orm(broker_model).json()
        )
        logging.info(f"Redis set result: {redis_set_result}")
        logging.info(f"session updated for user: {pya3_obj.user_id} in db and redis")
        return session_id
