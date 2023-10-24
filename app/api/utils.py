import asyncio
import logging
from datetime import datetime

from aioredis import Redis
from fastapi import HTTPException
from sqlalchemy import select

from app.database.models import BrokerModel
from app.database.session_manager.db_session import Database
from app.schemas.broker import BrokerSchema
from app.schemas.strategy import CFDStrategySchema
from app.schemas.strategy import StrategySchema
from app.schemas.trade import CFDPayloadSchema
from app.services.broker.alice_blue import Pya3Aliceblue
from app.utils.constants import REDIS_DATE_FORMAT
from app.utils.in_memory_cache import current_and_next_expiry_cache


async def get_expiry_list(async_redis_client, instrument_type, symbol):
    instrument_expiry = await async_redis_client.get(instrument_type)
    expiry_list = eval(instrument_expiry)[symbol]
    return [datetime.strptime(expiry, REDIS_DATE_FORMAT).date() for expiry in expiry_list]


async def get_current_and_next_expiry(async_redis_client, strategy_schema: StrategySchema):
    todays_date = datetime.now().date()
    if todays_date in current_and_next_expiry_cache:
        return current_and_next_expiry_cache[todays_date]

    is_today_expiry = False
    current_expiry_date = None
    next_expiry_date = None
    expiry_list = await get_expiry_list(
        async_redis_client, strategy_schema.instrument_type, strategy_schema.symbol
    )
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


async def update_session_token(pya3_obj: Pya3Aliceblue, async_redis_client: Redis):
    session_id = await pya3_obj.login_and_get_session_id()

    async with Database() as async_session:
        # get broker model from db filtered by username
        fetch_broker_query = await async_session.execute(
            select(BrokerModel).where(BrokerModel.username == pya3_obj.user_id)
        )
        broker_model = fetch_broker_query.scalars().one_or_none()
        broker_model.access_token = session_id
        await async_session.flush()

        # update redis cache with new session_id
        redis_set_result = await async_redis_client.set(
            str(broker_model.id), BrokerSchema.model_validate(broker_model).json()
        )
        logging.info(f"Redis set result: {redis_set_result}")
        logging.info(f"session updated for user: {pya3_obj.user_id} in db and redis")
        return session_id


def get_capital_cfd_lot_to_trade(cfd_strategy_schema: CFDStrategySchema, ongoing_profit_or_loss):
    try:
        drawdown_percentage = cfd_strategy_schema.max_drawdown / (
            cfd_strategy_schema.min_quantity * cfd_strategy_schema.margin_for_min_quantity
        )

        # Calculate the funds that can be traded in the current period
        tradable_funds = (cfd_strategy_schema.funds - ongoing_profit_or_loss) / (
            1 + drawdown_percentage
        )

        # Round down to the nearest multiple of the step size
        trade_quantity = (
            int(tradable_funds / cfd_strategy_schema.incremental_step_size)
            * cfd_strategy_schema.incremental_step_size
        )

        return trade_quantity
    except ZeroDivisionError:
        raise HTTPException(
            status_code=400, detail="Division by zero error in trade quantity calculation"
        )


async def get_capital_cfd_existing_profit_or_loss(
    client, cfd_payload_schema: CFDPayloadSchema
) -> float:
    get_all_positions_attempt = 1
    profit_or_loss = 0
    while get_all_positions_attempt < 10:
        try:
            # retrieving all positions throws 403 i.e. too many requests
            if positions := client.all_positions():
                for position in positions["positions"]:
                    if position["market"]["epic"] == cfd_payload_schema.instrument:
                        profit_or_loss += position["position"]["upl"]
            break
        except Exception as e:
            logging.error(
                f"[ {cfd_payload_schema.instrument} ]: Error occured while getting all positions : {e}"
            )
            get_all_positions_attempt += 1
            await asyncio.sleep(1)

    return profit_or_loss
