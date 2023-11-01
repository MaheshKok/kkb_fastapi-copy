import asyncio
import logging
from datetime import datetime

from _decimal import Decimal
from _decimal import getcontext
from aioredis import Redis
from fastapi import HTTPException
from sqlalchemy import select

from app.database.models import BrokerModel
from app.database.session_manager.db_session import Database
from app.schemas.broker import BrokerSchema
from app.schemas.strategy import CFDStrategySchema
from app.schemas.strategy import StrategySchema
from app.services.broker.alice_blue import Pya3Aliceblue
from app.services.broker.Capital import CapitalClient
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


def get_capital_cfd_lot_to_trade(
    cfd_strategy_schema: CFDStrategySchema, ongoing_profit_or_loss, available_funds
):
    to_update_profit_or_loss_in_db = 0
    # TODO: if funds reach below mranage_for_min_quantity, then we will not trade , handle it
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"

    getcontext().prec = 28  # Set a high precision
    try:
        # below code is to secure funds as per drawdown percentage
        # drawdown_percentage = Decimal(cfd_strategy_schema.max_drawdown) / (
        #     Decimal(cfd_strategy_schema.margin_for_min_quantity)
        # )
        #
        # # Calculate the funds that can be traded in the current period
        # funds_to_trade = (
        #     Decimal(cfd_strategy_schema.funds) + Decimal(ongoing_profit_or_loss)
        # ) / (1 + drawdown_percentage)
        #

        # Assume available funds are also positive
        if ongoing_profit_or_loss < 0:
            # open position with 95% of the funds available to avoid getting rejected due insufficient funds
            funds_to_trade = Decimal((cfd_strategy_schema.funds + ongoing_profit_or_loss) * 0.90)
            to_update_profit_or_loss_in_db = ongoing_profit_or_loss
        else:
            if available_funds < ongoing_profit_or_loss:
                funds_to_trade = Decimal((cfd_strategy_schema.funds + available_funds) * 0.90)
                to_update_profit_or_loss_in_db = available_funds
            else:
                funds_to_trade = Decimal(
                    (cfd_strategy_schema.funds + ongoing_profit_or_loss) * 0.90
                )
                to_update_profit_or_loss_in_db = ongoing_profit_or_loss

        # Calculate the quantity that can be traded in the current period
        approx_quantity_to_trade = funds_to_trade / (
            Decimal(cfd_strategy_schema.margin_for_min_quantity)
            / Decimal(cfd_strategy_schema.min_quantity)
        )

        # Round down to the nearest multiple of
        # cfd_strategy_schema.min_quantity + cfd_strategy_schema.incremental_step_size
        to_round_down = Decimal(cfd_strategy_schema.min_quantity) + Decimal(
            cfd_strategy_schema.incremental_step_size
        )
        quantity_to_trade = (approx_quantity_to_trade // to_round_down) * to_round_down

        # Convert the result back to a float for consistency with your existing code
        result = float(quantity_to_trade)
        logging.info(
            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : lots to open [ {result} ]"
        )
        logging.info(
            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ]: to_update_profit_or_loss_in_db [ {to_update_profit_or_loss_in_db}]"
        )
        return result, to_update_profit_or_loss_in_db

    except ZeroDivisionError:
        raise HTTPException(
            status_code=400, detail="Division by zero error in trade quantity calculation"
        )


async def get_all_positions(
    client: CapitalClient, cfd_strategy_schema: CFDStrategySchema
) -> dict:
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"

    get_all_positions_attempt = 1
    while get_all_positions_attempt < 10:
        try:
            # retrieving all positions throws 403 i.e. too many requests
            return client.all_positions()
        except Exception as e:
            response, status_code, text = e.args
            if status_code == 429:
                get_all_positions_attempt += 1
                await asyncio.sleep(2)
            elif status_code == 400:
                get_all_positions_attempt += 1
                await asyncio.sleep(2)
            else:
                logging.error(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Error occured while getting all positions {status_code} { text}"
                )
                break
    else:
        logging.error(
            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Error occured while getting all positions {text}"
        )


async def get_capital_cfd_existing_profit_or_loss(
    client, cfd_strategy_schema: CFDStrategySchema
) -> tuple[float, float]:
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"

    profit_or_loss = 0
    existing_lot = 0
    positions = await get_all_positions(client, cfd_strategy_schema)
    for position in positions["positions"]:
        if position["market"]["epic"] == cfd_strategy_schema.instrument:
            profit_or_loss += position["position"]["upl"]
            existing_lot += position["position"]["size"]

    logging.info(
        f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : existing profit: [ {profit_or_loss} ]"
    )
    logging.info(
        f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : existing lot: [ {existing_lot} ]"
    )
    return round(profit_or_loss, 2), existing_lot


async def get_capital_dot_com_available_funds(
    client, cfd_strategy_schema: CFDStrategySchema
) -> float:
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"

    get_all_positions_attempt = 1
    while get_all_positions_attempt < 10:
        try:
            # retrieving all positions throws 403 i.e. too many requests
            return client.all_accounts()[0]["balance"]["available"]
        except Exception as e:
            response, status_code, text = e.args
            if status_code == 429:
                get_all_positions_attempt += 1
                await asyncio.sleep(2)
            elif status_code == 400:
                get_all_positions_attempt += 1
                await asyncio.sleep(2)
            else:
                logging.error(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Error occured while getting all positions {status_code} {text}"
                )
                break
    else:
        logging.error(
            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Error occured while getting all positions {text}"
        )
