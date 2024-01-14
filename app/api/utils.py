import asyncio
import logging
from datetime import datetime

import httpx
from _decimal import ROUND_DOWN
from _decimal import Decimal
from _decimal import getcontext
from aioredis import Redis
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy import update

from app.broker.alice_blue import Pya3Aliceblue
from app.broker.AsyncCapital import AsyncCapitalClient
from app.database.models import BrokerModel
from app.database.models import CFDStrategyModel
from app.database.session_manager.db_session import Database
from app.schemas.broker import BrokerSchema
from app.schemas.strategy import CFDStrategySchema
from app.schemas.strategy import StrategySchema
from app.schemas.trade import CFDPayloadSchema
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


async def get_capital_cfd_lot_to_trade(
    client, cfd_strategy_schema: CFDStrategySchema, ongoing_profit_or_loss
):
    funds_to_use = await get_available_funds(client, cfd_strategy_schema)

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

        if funds_to_use < ongoing_profit_or_loss:
            funds_to_trade = Decimal(cfd_strategy_schema.funds + (funds_to_use * 0.95))
            to_update_profit_or_loss_in_db = funds_to_use
        else:
            funds_to_trade = Decimal(cfd_strategy_schema.funds + (ongoing_profit_or_loss * 0.95))
            to_update_profit_or_loss_in_db = ongoing_profit_or_loss

        funds_for_1_contract = Decimal(cfd_strategy_schema.margin_for_min_quantity) / Decimal(
            cfd_strategy_schema.min_quantity
        )

        if not cfd_strategy_schema.compounding:
            funds_required_for_contracts = (
                Decimal(cfd_strategy_schema.contracts) * funds_for_1_contract
            )
            funds_available = Decimal(cfd_strategy_schema.funds) + Decimal(
                to_update_profit_or_loss_in_db
            )
            if funds_required_for_contracts < funds_available:
                return cfd_strategy_schema.contracts, to_update_profit_or_loss_in_db
            else:
                contracts_in_available_funds = funds_available / funds_for_1_contract
                # Add rounding here
                contracts_in_available_funds = contracts_in_available_funds.quantize(
                    Decimal("0.01"), rounding=ROUND_DOWN
                )
                return float(contracts_in_available_funds), to_update_profit_or_loss_in_db

        # Calculate the quantity that can be traded in the current period
        approx_lots_to_trade = funds_to_trade / funds_for_1_contract

        # Round down to the nearest multiple of
        # cfd_strategy_schema.min_quantity + cfd_strategy_schema.incremental_step_size
        to_round_down = Decimal(cfd_strategy_schema.min_quantity) + Decimal(
            cfd_strategy_schema.incremental_step_size
        )
        lots_to_trade = (approx_lots_to_trade // to_round_down) * to_round_down

        # Add rounding here
        lots_to_trade = lots_to_trade.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        # Convert the result back to a float for consistency with your existing code
        lots_to_trade = float(lots_to_trade)
        logging.info(
            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : lots to open [ {lots_to_trade} ], to_update_profit_or_loss_in_db [ {to_update_profit_or_loss_in_db} ]"
        )
        return lots_to_trade, to_update_profit_or_loss_in_db

    except ZeroDivisionError:
        raise HTTPException(
            status_code=400, detail="Division by zero error in trade quantity calculation"
        )


async def get_all_positions(
    client: AsyncCapitalClient, cfd_strategy_schema: CFDStrategySchema
) -> dict:
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"

    get_all_positions_attempt = 1
    while get_all_positions_attempt < 10:
        try:
            # retrieving all positions throws 403 i.e. too many requests
            all_positions = await client.all_positions()
            return all_positions
        except httpx.HTTPStatusError as error:
            response = error.response
            status_code, text = response.status_code, response.text
            if status_code == 429:
                logging.warning(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {get_all_positions_attempt} ] Error occured while getting all positions {status_code} {text}"
                )
                await client.__log_out__()
                get_all_positions_attempt += 1
                await asyncio.sleep(2)
            elif status_code == 400:
                logging.warning(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {get_all_positions_attempt} ] Error occured while getting all positions {status_code} {text}"
                )
                await client.__log_out__()
                get_all_positions_attempt += 1
                await asyncio.sleep(2)
            else:
                logging.error(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {get_all_positions_attempt} ] Error occured while getting all positions {status_code} {text}"
                )
                break
    else:
        logging.error(
            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : All attemps exhausted in getting all positions, Error {status_code} {text}"
        )


async def get_all_open_orders(
    client: AsyncCapitalClient, cfd_strategy_schema: CFDStrategySchema
) -> list:
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"

    get_all_orders_attempt = 1
    while get_all_orders_attempt < 10:
        try:
            working_orders = await client.all_working_orders()
            if working_orders:
                return working_orders["workingOrders"]
            return []
        except httpx.HTTPStatusError as error:
            response = error.response
            status_code, text = response.status_code, response.text
            if status_code == 429:
                logging.warning(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {get_all_orders_attempt} ] Error occured while getting all orders {status_code} {text}"
                )
                await client.__log_out__()
                get_all_orders_attempt += 1
                await asyncio.sleep(2)
            elif status_code == 400:
                logging.warning(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {get_all_orders_attempt} ] Error occured while getting all orders {status_code} {text}"
                )
                await client.__log_out__()
                get_all_orders_attempt += 1
                await asyncio.sleep(2)
            else:
                logging.error(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {get_all_orders_attempt} ] Error occured while getting all orders {status_code} {text}"
                )
                break
    else:
        logging.error(
            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : All attemps exhausted in getting all orders, Error {status_code} {text}"
        )


async def get_capital_cfd_existing_profit_or_loss(
    client, cfd_strategy_schema: CFDStrategySchema
) -> tuple[int, int, str | None]:
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"
    direction = None
    profit_or_loss = 0
    existing_lot = 0
    positions = await get_all_positions(client, cfd_strategy_schema)
    for position in positions["positions"]:
        if position["market"]["epic"] == cfd_strategy_schema.instrument:
            profit_or_loss += position["position"]["upl"]
            existing_lot += position["position"]["size"]
            direction = position["position"]["direction"]

    logging.info(
        f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : existing position - profit: [ {profit_or_loss} ], lot: [ {existing_lot} ], direction: [ {direction} ]"
    )
    return round(profit_or_loss, 2), existing_lot, direction


async def get_available_funds(client, cfd_strategy_schema: CFDStrategySchema) -> float:
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"

    get_all_positions_attempt = 1
    while get_all_positions_attempt < 10:
        try:
            all_accounts = await client.all_accounts()
            available_funds = all_accounts["accounts"][0]["balance"]["available"]
            if cfd_strategy_schema.compounding:
                available_funds = round(
                    available_funds * cfd_strategy_schema.funds_usage_percent, 2
                )
            return available_funds
        except httpx.HTTPStatusError as error:
            response = error.response
            status_code, text = response.status_code, response.text

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


async def update_capital_funds(
    *, cfd_strategy_schema: CFDStrategySchema, profit_or_loss: float, demo_or_live: str
):
    log_profit_or_loss = "profit" if profit_or_loss > 0 else "loss"

    updated_funds = round(cfd_strategy_schema.funds + profit_or_loss, 2)
    async with Database() as async_session:
        await async_session.execute(
            update(CFDStrategyModel)
            .where(CFDStrategyModel.id == cfd_strategy_schema.id)
            .values(funds=updated_funds)
        )
        await async_session.commit()
        logging.info(
            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : updated funds balance to [ {updated_funds} ] after {log_profit_or_loss}: {profit_or_loss} "
        )


async def open_order_found(
    *,
    client: AsyncCapitalClient,
    demo_or_live: str,
    cfd_strategy_schema: CFDStrategySchema,
    cfd_payload_schema: CFDPayloadSchema,
    lots_size: float,
):
    logging.info(f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : getting open order.")
    if open_orders := await get_all_open_orders(client, cfd_strategy_schema):
        for open_order in open_orders:
            instrument, direction = (
                open_order["workingOrderData"]["epic"],
                open_order["workingOrder"]["direction"],
            )
            if (
                instrument == cfd_strategy_schema.instrument
                and direction != cfd_payload_schema.direction
            ):
                logging.warning(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Open order detected for [ {lots_size} ] Lots in [ {direction} ] direction"
                )
                return True
    logging.info(f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : open order not found")
    return False


async def find_position(
    *,
    client: AsyncCapitalClient,
    demo_or_live: str,
    cfd_strategy_schema: CFDStrategySchema,
    current_open_lots: float,
    action: str,
):
    if positions := await get_all_positions(client, cfd_strategy_schema):
        for position in positions["positions"]:
            if position["market"]["epic"] == cfd_strategy_schema.instrument:
                return position
        else:
            logging.warning(
                f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : lots [ {current_open_lots} ] are {action} as no existing position found."
            )
            return False
    else:
        logging.warning(
            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Assuming lots are {action} as no existing position found."
        )
        return False


async def close_capital_lots(
    *,
    client: AsyncCapitalClient,
    lots_to_close: float,
    cfd_strategy_schema: CFDStrategySchema,
    cfd_payload_schema: CFDPayloadSchema,
    demo_or_live: str,
    profit_or_loss: float,
):
    close_lots_attempt = 1
    while close_lots_attempt <= 10:
        try:
            response = await client.create_position(
                epic=cfd_strategy_schema.instrument,
                direction=cfd_payload_schema.direction,
                size=lots_to_close,
            )

            response_json = response.json()
            if response_json["dealStatus"] == "ACCEPTED":
                msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : successfully closed [  {lots_to_close} ] trades."
                logging.info(msg)
                return False
            elif response_json["dealStatus"] == "REJECTED":
                if response_json["rejectReason"] == "THROTTLING":
                    msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {close_lots_attempt} ] throttled while closing open lots [ {lots_to_close} ] response:  {response_json}"
                    logging.warning(msg)
                    close_lots_attempt += 1
                    await asyncio.sleep(2)
                    continue
                logging.warning(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {close_lots_attempt} ], rejected closing open lots [ {lots_to_close} ] response:  {response_json}. Attempting again to close"
                )
            else:
                msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {close_lots_attempt} ] deal status: {response_json}"
                logging.error(msg)
        except httpx.HTTPStatusError as error:
            response_json = error.response
            status_code, text = response_json.status_code, response_json.text
            if status_code in [400, 404, 429]:
                logging.warning(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {close_lots_attempt} ] while closing lots {status_code} {text}"
                )
                await asyncio.sleep(3)
                logging.info(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] may be lots are closed , so fetching all positions again and verifying the same"
                )

                _open_order_found = await open_order_found(
                    client=client,
                    demo_or_live=demo_or_live,
                    cfd_strategy_schema=cfd_strategy_schema,
                    cfd_payload_schema=cfd_payload_schema,
                    lots_size=lots_to_close,
                )

                if _open_order_found:
                    break

                await asyncio.sleep(1)
                position_found = await find_position(
                    client=client,
                    demo_or_live=demo_or_live,
                    cfd_strategy_schema=cfd_strategy_schema,
                    current_open_lots=lots_to_close,
                    action="closed",
                )

                if position_found:
                    if (
                        position_found["position"]["direction"]
                        == cfd_payload_schema.direction.upper()
                    ):
                        logging.warning(
                            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Lots [ {lots_to_close} ] are reversed in [ {cfd_payload_schema.direction} ] direction. so NO need to open lots again"
                        )
                        await update_capital_funds(
                            cfd_strategy_schema=cfd_strategy_schema,
                            demo_or_live=demo_or_live,
                            profit_or_loss=profit_or_loss,
                        )
                        # TODO: try to open lots with the profit gained
                        break
                    else:
                        logging.warning(
                            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Lots [ {lots_to_close} ] are not closed. Hence trying again to close them"
                        )
                        close_lots_attempt += 1
                        await asyncio.sleep(3)
                else:
                    logging.warning(
                        f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Lots [ {lots_to_close} ] are closed as no position found."
                    )
                    break
            else:
                msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {close_lots_attempt} ] Error occured while closing open lots, Error: {text}"
                logging.error(msg)
                return False


async def open_capital_lots(
    *,
    client: AsyncCapitalClient,
    cfd_strategy_schema: CFDStrategySchema,
    cfd_payload_schema: CFDPayloadSchema,
    demo_or_live: str,
    profit_or_loss: float,
):
    lots_to_open, update_profit_or_loss_in_db = await get_capital_cfd_lot_to_trade(
        client, cfd_strategy_schema, profit_or_loss
    )

    place_order_attempt = 1
    while place_order_attempt < 10:
        try:
            response = await client.create_position(
                epic=cfd_strategy_schema.instrument,
                direction=cfd_payload_schema.direction,
                size=lots_to_open,
            )

            response_json = response.json()
            if response_json["dealStatus"] == "REJECTED":
                if response_json["rejectReason"] == "THROTTLING":
                    # handled rejectReason: 'THROTTLING' i.e. try again
                    msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {place_order_attempt} ] throttled while opening lots [ {lots_to_open} ] response:  {response_json}"
                    logging.warning(msg)
                    logging.info(
                        f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] attempting again to open lots"
                    )
                    place_order_attempt += 1
                    await client.__log_out__()
                    await asyncio.sleep(2)
                    continue
                elif response_json["rejectReason"] == "RISK_CHECK":
                    # handle rejectReason: RISK_CHECK i.e. calculate lots to open again as available funds are updated
                    # calculate lots to open again as available funds are updated
                    msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {place_order_attempt} ] RISK_CHECK while opening lots [ {lots_to_open} ] response:  {response_json}"
                    logging.warning(msg)
                    logging.info(
                        f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] calculating lots to open again as available funds are updated"
                    )
                    (
                        lots_to_open,
                        update_profit_or_loss_in_db,
                    ) = await get_capital_cfd_lot_to_trade(
                        client, cfd_strategy_schema, profit_or_loss
                    )
                    place_order_attempt += 1
                    await client.__log_out__()
                    await asyncio.sleep(1)
                    continue
                else:
                    logging.error(
                        f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {place_order_attempt} ] rejected, deal status: {response_json['dealStatus']}, reason: {response_json['rejectReason']}, status: {response_json['status']}"
                    )
                    return response_json
            elif response_json["dealStatus"] == "ACCEPTED":
                long_or_short = "LONG" if cfd_payload_schema.direction == "buy" else "SHORT"
                msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : successfully [ {long_or_short}  {lots_to_open} ] trades."
                logging.info(msg)
            else:
                msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {place_order_attempt} ] Error in placing open lots, deal status: {response_json}"
                logging.error(msg)

            if update_profit_or_loss_in_db:
                # update funds balance
                await update_capital_funds(
                    cfd_strategy_schema=cfd_strategy_schema,
                    demo_or_live=demo_or_live,
                    profit_or_loss=update_profit_or_loss_in_db,
                )
            else:
                logging.info(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : No profit or loss to update in db"
                )
            return msg
        except httpx.HTTPStatusError as error:
            response_json = error.response
            status_code, text = response_json.status_code, response_json.text
            if status_code == 429:
                logging.warning(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {place_order_attempt} ] throttled while opening lots [ {lots_to_open} ] {status_code} {text}"
                )
                logging.info(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : attempting again to open lots"
                )
                # too many requests
                place_order_attempt += 1
                await client.__log_out__()
                await asyncio.sleep(2)
            elif status_code in [400, 404]:
                # # if it throws 404 exception saying dealreference not found then try to fetch all positions
                # # and see if order is placed and if not then try it again and if it is placed then skip it
                logging.warning(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt [ {place_order_attempt} ] while opening lots {status_code} {text}"
                )
                await asyncio.sleep(2)
                logging.info(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] may be lots are opened , so fetching all positions againa and verifying the same"
                )

                _open_order_found = await open_order_found(
                    client=client,
                    demo_or_live=demo_or_live,
                    cfd_strategy_schema=cfd_strategy_schema,
                    cfd_payload_schema=cfd_payload_schema,
                    lots_size=lots_to_open,
                )

                if _open_order_found:
                    break

                position_found = await find_position(
                    client=client,
                    demo_or_live=demo_or_live,
                    cfd_strategy_schema=cfd_strategy_schema,
                    current_open_lots=lots_to_open,
                    action="open",
                )

                if position_found:
                    response_direction = position_found["position"]["direction"]
                    response_lots = position_found["position"]["size"]
                    if (
                        position_found["position"]["direction"]
                        == cfd_payload_schema.direction.upper()
                    ):
                        long_or_short = (
                            "LONG" if cfd_payload_schema.direction == "buy" else "SHORT"
                        )
                        msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : successfully [ {long_or_short}  {lots_to_open} ] trades."
                        logging.info(msg)

                        await update_capital_funds(
                            cfd_strategy_schema=cfd_strategy_schema,
                            demo_or_live=demo_or_live,
                            profit_or_loss=profit_or_loss,
                        )
                        # TODO: try to open lots with the profit gained
                        break
                    else:
                        # very rare case where lots are still in current direction.
                        # trying to close them by updating "lots_to_open" to the lots from position response
                        logging.warning(
                            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : lots are still in current [ {response_direction} ] direction. trying to close [ {response_lots} ] lots."
                        )
                        lots_to_open = response_lots
                        place_order_attempt += 1
                        await asyncio.sleep(3)
                else:
                    place_order_attempt += 1
                    await asyncio.sleep(1)
            else:
                msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Error occured while opening lots, Error: {text}"
                logging.error(msg)
                return msg


async def handle_exception(
    client,
    status_code,
    demo_or_live,
    cfd_strategy_schema,
    cfd_payload_schema,
    lots_to_manage,
    is_opening,
    profit_or_loss,
):
    logging.warning(
        f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Attempt while {( 'opening' if is_opening else 'closing' )} lots {status_code}"
    )

    # Check for open orders
    open_order_found = False
    if open_orders := await get_all_open_orders(client, cfd_strategy_schema):
        for open_order in open_orders:
            instrument, direction = (
                open_order["workingOrderData"]["epic"],
                open_order["workingOrder"]["direction"],
            )
            if (
                instrument == cfd_strategy_schema.instrument
                and direction != cfd_payload_schema.direction
            ):
                logging.warning(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : open order found for lots [ {lots_to_manage} ] in [ {direction} ] direction."
                )
                open_order_found = True
                break

    if open_order_found:
        return

    # Check for existing positions
    if positions := await get_all_positions(client, cfd_strategy_schema):
        for position in positions["positions"]:
            if position["market"]["epic"] == cfd_strategy_schema.instrument:
                response_position_direction = position["position"]["direction"]
                if response_position_direction == cfd_payload_schema.direction.upper():
                    if is_opening:
                        msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : successfully [ {response_position_direction} ] {position['position']['size']} trades"
                        logging.info(msg)
                        return msg
                    elif not is_opening:
                        logging.warning(
                            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Lots [ {lots_to_manage} ] are reversed in [ {cfd_payload_schema.direction} ] direction. So no need to open lots again"
                        )
                        await update_capital_funds(
                            cfd_strategy_schema=cfd_strategy_schema,
                            demo_or_live=demo_or_live,
                            profit_or_loss=profit_or_loss,
                        )
                        return True
                else:
                    logging.warning(
                        f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : lots are not closed, hence trying to close lots [ {lots_to_manage} ] again"
                    )
    else:
        logging.warning(
            f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : Assuming lots [ {lots_to_manage} ] are {( 'opened' if is_opening else 'closed' )}"
        )
