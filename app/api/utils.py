import asyncio
import io
import logging
from datetime import datetime

import httpx
import pandas as pd
from _decimal import ROUND_DOWN
from _decimal import Decimal
from _decimal import getcontext
from aioredis import Redis
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy import update

from app.broker.AsyncCapital import AsyncCapitalClient
from app.broker.AsyncPya3AliceBlue import AsyncPya3Aliceblue
from app.database.models import BrokerModel
from app.database.models import CFDStrategyModel
from app.database.session_manager.db_session import Database
from app.schemas.broker import BrokerSchema
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.strategy import CFDStrategySchema
from app.schemas.strategy import StrategySchema
from app.schemas.trade import CFDPayloadSchema
from app.utils.constants import REDIS_DATE_FORMAT


async def get_expiry_dict_from_alice_blue():
    api = "https://v2api.aliceblueonline.com/restpy/static/contract_master/NFO.csv"

    response = await httpx.AsyncClient().get(api)
    data_stream = io.StringIO(response.text)
    df = pd.read_csv(data_stream)
    result = {}
    for (instrument_type, symbol), group in df.groupby(["Instrument Type", "Symbol"]):
        if instrument_type not in result:
            result[instrument_type] = {}
        expiry_dates = sorted(set(group["Expiry Date"].tolist()))
        result[instrument_type][symbol] = expiry_dates

    return result


async def get_expiry_list_from_redis(async_redis_client, instrument_type, symbol):
    instrument_expiry = await async_redis_client.get(instrument_type)
    expiry_list = eval(instrument_expiry)[symbol]
    return [datetime.strptime(expiry, REDIS_DATE_FORMAT).date() for expiry in expiry_list]


async def get_current_and_next_expiry_from_redis(
    async_redis_client, strategy_schema: StrategySchema
):
    todays_date = datetime.now().date()

    is_today_expiry = False
    current_expiry_date = None
    next_expiry_date = None
    expiry_list = await get_expiry_list_from_redis(
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

    return current_expiry_date, next_expiry_date, is_today_expiry


async def get_current_and_next_expiry_from_alice_blue(symbol: str):
    todays_date = datetime.now().date()

    is_today_expiry = False
    current_expiry_date = None
    next_expiry_date = None
    expiry_dict = await get_expiry_dict_from_alice_blue()
    expiry_list = expiry_dict[InstrumentTypeEnum.OPTIDX][symbol]
    expiry_datetime_obj_list = [
        datetime.strptime(expiry, REDIS_DATE_FORMAT).date() for expiry in expiry_list
    ]
    for index, expiry_date in enumerate(expiry_datetime_obj_list):
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

    return current_expiry_date, next_expiry_date, is_today_expiry


async def update_session_token(pya3_obj: AsyncPya3Aliceblue, async_redis_client: Redis):
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


def get_lots_to_trade_and_profit_or_loss(
    funds_to_use,
    strategy_schema: CFDStrategySchema | StrategySchema,
    ongoing_profit_or_loss,
    crucial_details: str = None,
):
    def _get_lots_to_trade(strategy_funds_to_trade, strategy_schema):
        # below is the core of this function do not mendle with it
        # Calculate the quantity that can be traded in the current period
        approx_lots_to_trade = strategy_funds_to_trade * (
            Decimal(strategy_schema.min_quantity)
            / Decimal(strategy_schema.margin_for_min_quantity)
        )

        to_increment = Decimal(strategy_schema.incremental_step_size)
        closest_lots_to_trade = (approx_lots_to_trade // to_increment) * to_increment

        while closest_lots_to_trade + to_increment <= approx_lots_to_trade:
            closest_lots_to_trade += to_increment

        if closest_lots_to_trade + to_increment == approx_lots_to_trade:
            lots_to_trade = closest_lots_to_trade + to_increment
        else:
            lots_to_trade = closest_lots_to_trade

        # Add rounding here
        lots_to_trade = lots_to_trade.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        # Convert the result back to a float for consistency with your existing code
        lots_to_trade = float(lots_to_trade)
        return lots_to_trade

    # TODO: if funds reach below mranage_for_min_quantity, then we will not trade , handle it
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

        # i think below code doesnt make any sense as i have seen if available funds are in negative still i can trade in broker,
        # dont know how it works in indian broker like zerodha , keeping it for now
        # if funds_to_use < ongoing_profit_or_loss:
        #     funds_to_trade = Decimal(strategy_schema.funds + (funds_to_use * 0.95))
        #     to_update_profit_or_loss_in_db = funds_to_use
        # else:
        #     funds_to_trade = Decimal(strategy_schema.funds + (ongoing_profit_or_loss * 0.95))
        #     to_update_profit_or_loss_in_db = ongoing_profit_or_loss

        strategy_funds_to_trade = Decimal(
            (strategy_schema.funds + ongoing_profit_or_loss) * strategy_schema.funds_usage_percent
        )
        strategy_funds_to_trade = round(strategy_funds_to_trade, 2)
        logging.info(
            f"[ {crucial_details} ] - strategy_funds_to_trade: {strategy_funds_to_trade}"
        )

        if strategy_funds_to_trade < Decimal(strategy_schema.margin_for_min_quantity):
            logging.info(
                f"[ {crucial_details} ] - strategy_funds_to_trade: [ {strategy_funds_to_trade} ] is less than margin for min quantity: {strategy_schema.margin_for_min_quantity}"
            )
            strategy_funds_to_trade = Decimal(strategy_schema.margin_for_min_quantity)

        to_update_profit_or_loss_in_db = ongoing_profit_or_loss
        if not strategy_schema.compounding:
            logging.info(
                f"[ {crucial_details} ] - Compounding is not enabled, so we will trade fixed contracts: [ {strategy_schema.contracts} ]"
            )
            funds_required_for_contracts = Decimal(
                (strategy_schema.margin_for_min_quantity / strategy_schema.min_quantity)
                * strategy_schema.contracts
            )
            available_funds = Decimal(strategy_schema.funds + ongoing_profit_or_loss)
            if funds_required_for_contracts <= available_funds:
                lots_to_trade = strategy_schema.contracts
                logging.info(
                    f"[ {crucial_details} ] - Available Funds: [ {available_funds} ] are more than funds required for contracts: [ {funds_required_for_contracts} ]"
                )
            else:
                lots_to_trade = _get_lots_to_trade(available_funds, strategy_schema)
                logging.info(
                    f"[ {crucial_details} ] - Available Funds: [ {available_funds} ] are less than funds required for contracts: [ {funds_required_for_contracts} ]. So we will trade [ {lots_to_trade} ] contracts"
                )
        else:
            lots_to_trade = _get_lots_to_trade(strategy_funds_to_trade, strategy_schema)
            logging.info(
                f"[ {crucial_details} ] - Compounding is enabled and we can trade [ {lots_to_trade} ] contracts in [ {strategy_funds_to_trade} ] funds"
            )

        logging.info(
            f"[ {crucial_details} ] - lots to open [ {lots_to_trade} ], to_update_profit_or_loss_in_db [ {to_update_profit_or_loss_in_db} ]"
        )
        return lots_to_trade, to_update_profit_or_loss_in_db

    except ZeroDivisionError:
        raise HTTPException(
            status_code=400, detail="Division by zero error in trade quantity calculation"
        )


async def get_all_positions(
    client: AsyncCapitalClient, cfd_strategy_schema: CFDStrategySchema, crucial_details: str
) -> dict:
    get_all_positions_attempt = 1
    error = None
    while get_all_positions_attempt < 10:
        try:
            # retrieving all positions throws
            # 429 i.e. {"errorCode":"error.too-many.requests"}
            # 401: {"errorCode":"error.invalid.details"},
            # 400: dont know
            all_positions = await client.all_positions()
            return all_positions
        except httpx.HTTPStatusError as http_status_error:
            response = http_status_error.response
            status_code, error = response.status_code, response.text
            logging.warning(
                f"[ {crucial_details} ] - Attempt [ {get_all_positions_attempt} ] HTTPStatusError occured while getting all positions {status_code} {error}"
            )
            await client.__log_out__()
            get_all_positions_attempt += 1
            await asyncio.sleep(1)
        except Exception as exception_error:
            error = exception_error
            logging.warning(
                f"[ {crucial_details} ] - Attempt [ {get_all_positions_attempt} ] Exception Error occured while getting all positions {error}"
            )
            get_all_positions_attempt += 1
            await asyncio.sleep(1)
    else:
        logging.error(
            f"[ {crucial_details} ] - All attemps exhausted in getting all positions, Error: {error}"
        )
        raise HTTPException(
            status_code=400, detail="All attemps exhausted in getting all positions"
        )


async def get_all_open_orders(client: AsyncCapitalClient, crucial_details: str) -> list:
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
                    f"[ {crucial_details} ] - Attempt [ {get_all_orders_attempt} ] Error occured while getting all orders {status_code} {text}"
                )
                await client.__log_out__()
                get_all_orders_attempt += 1
                await asyncio.sleep(2)
            elif status_code == 400:
                logging.warning(
                    f"[ {crucial_details} ] - Attempt [ {get_all_orders_attempt} ] Error occured while getting all orders {status_code} {text}"
                )
                await client.__log_out__()
                get_all_orders_attempt += 1
                await asyncio.sleep(2)
            else:
                logging.error(
                    f"[ {crucial_details} ] - Attempt [ {get_all_orders_attempt} ] Error occured while getting all orders {status_code} {text}"
                )
                break
    else:
        logging.error(
            f"[ {crucial_details} ] - All attemps exhausted in getting all orders, Error {status_code} {text}"
        )


async def get_capital_cfd_existing_profit_or_loss(
    client: AsyncCapitalClient, cfd_strategy_schema: CFDStrategySchema, crucial_details: str
) -> tuple[int, int, str | None]:
    direction = None
    profit_or_loss_value = 0
    existing_lot = 0
    positions = await get_all_positions(client, cfd_strategy_schema, crucial_details)
    for position in positions["positions"]:
        if position["market"]["epic"] == cfd_strategy_schema.instrument:
            profit_or_loss_value += position["position"]["upl"]
            existing_lot += position["position"]["size"]
            direction = position["position"]["direction"]

    profit_or_loss_str = "profit" if profit_or_loss_value > 0 else "loss"
    logging.info(
        f"[ {crucial_details} ] - current lots: [ {existing_lot} ] {profit_or_loss_str}: [ {profit_or_loss_value} ], direction: [ {direction} ] to be closed"
    )
    return round(profit_or_loss_value, 2), existing_lot, direction


async def get_funds_to_use(
    client, cfd_strategy_schema: CFDStrategySchema, crucial_details: str
) -> float:
    get_all_accounts_attempt = 1
    while get_all_accounts_attempt < 10:
        try:
            all_accounts = await client.all_accounts()
            available_funds = all_accounts["accounts"][0]["balance"]["available"]
            return available_funds

        except httpx.HTTPStatusError as error:
            response = error.response
            status_code, text = response.status_code, response.text
            # known error code 400, 401, and 429
            # 400: invalid credentials
            # 401: {"errorCode":"error.invalid.details"}
            # 429: {"errorCode":"error.too-many.requests"}
            get_all_accounts_attempt += 1
            await asyncio.sleep(1)
            logging.warning(
                f"[ {crucial_details} ] - Attemp [ {get_all_accounts_attempt} ] HTTPStatusError occured while getting all accounts {status_code} {text}"
            )
    else:
        logging.error(
            f"[ {crucial_details} ] - Error occured while getting all accounts {status_code} {text}"
        )


async def update_cfd_strategy_funds(
    *, cfd_strategy_schema: CFDStrategySchema, profit_or_loss: float, crucial_details: str
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
            f"[ {crucial_details} ] - funds balance [ {cfd_strategy_schema.funds} ] got updated to [ {updated_funds} ] after {log_profit_or_loss}: {profit_or_loss} "
        )


async def open_order_found(
    *,
    client: AsyncCapitalClient,
    cfd_strategy_schema: CFDStrategySchema,
    cfd_payload_schema: CFDPayloadSchema,
    lots_size: float,
    crucial_details: str,
):
    logging.info(f"[ {crucial_details} ] : getting open order.")
    if open_orders := await get_all_open_orders(client, crucial_details):
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
                    f"[ {crucial_details} ] - Open order detected for [ {lots_size} ] Lots in [ {direction} ] direction"
                )
                return True
    logging.info(f"[ {crucial_details} ] : open order not found")
    return False


async def find_position(
    *,
    client: AsyncCapitalClient,
    demo_or_live: str,
    cfd_strategy_schema: CFDStrategySchema,
    current_open_lots: float,
    action: str,
    crucial_details: str,
):
    if positions := await get_all_positions(client, cfd_strategy_schema, crucial_details):
        for position in positions["positions"]:
            if position["market"]["epic"] == cfd_strategy_schema.instrument:
                return position
        else:
            logging.warning(
                f"[ {crucial_details} ] - lots [ {current_open_lots} ] are {action} as no existing position found."
            )
            return False
    else:
        logging.warning(
            f"[ {crucial_details} ] - Assuming lots are {action} as no existing position found."
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
    crucial_details: str,
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
                msg = f"[ {crucial_details} ] - successfully closed [  {lots_to_close} ] trades."
                logging.info(msg)
                return False
            elif response_json["dealStatus"] == "REJECTED":
                if response_json["rejectReason"] == "THROTTLING":
                    msg = f"[ {crucial_details} ] - Attempt [ {close_lots_attempt} ] throttled while closing open lots [ {lots_to_close} ] response:  {response_json}"
                    logging.warning(msg)
                    close_lots_attempt += 1
                    await asyncio.sleep(2)
                    continue
                logging.warning(
                    f"[ {crucial_details} ] - Attempt [ {close_lots_attempt} ], rejected closing open lots [ {lots_to_close} ] response:  {response_json}. Attempting again to close"
                )
            else:
                msg = f"[ {crucial_details} ] - Attempt [ {close_lots_attempt} ] deal status: {response_json}"
                logging.error(msg)
        except httpx.HTTPStatusError as error:
            response_json = error.response
            status_code, text = response_json.status_code, response_json.text
            if status_code in [400, 404, 429]:
                logging.warning(
                    f"[ {crucial_details} ] - Attempt [ {close_lots_attempt} ] while closing lots {status_code} {text}"
                )
                await asyncio.sleep(3)
                logging.info(
                    f"[ {crucial_details} ] - may be lots are closed , so fetching all positions again and verifying the same"
                )

                _open_order_found = await open_order_found(
                    client=client,
                    cfd_strategy_schema=cfd_strategy_schema,
                    cfd_payload_schema=cfd_payload_schema,
                    lots_size=lots_to_close,
                    crucial_details=crucial_details,
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
                    crucial_details=crucial_details,
                )

                if position_found:
                    if (
                        position_found["position"]["direction"]
                        == cfd_payload_schema.direction.upper()
                    ):
                        logging.warning(
                            f"[ {crucial_details} ] - Lots [ {lots_to_close} ] are reversed in [ {cfd_payload_schema.direction} ] direction. so NO need to open lots again"
                        )
                        await update_cfd_strategy_funds(
                            cfd_strategy_schema=cfd_strategy_schema,
                            crucial_details=crucial_details,
                            profit_or_loss=profit_or_loss,
                        )
                        # TODO: try to open lots with the profit gained
                        break
                    else:
                        logging.warning(
                            f"[ {crucial_details} ] - Lots [ {lots_to_close} ] are not closed. Hence trying again to close them"
                        )
                        close_lots_attempt += 1
                        await asyncio.sleep(3)
                else:
                    logging.warning(
                        f"[ {crucial_details} ] - Lots [ {lots_to_close} ] are closed as no position found."
                    )
                    break
            else:
                msg = f"[ {crucial_details} ] - Attempt [ {close_lots_attempt} ] Error occured while closing open lots, Error: {text}"
                logging.error(msg)
                return False


async def open_capital_lots(
    *,
    client: AsyncCapitalClient,
    cfd_strategy_schema: CFDStrategySchema,
    cfd_payload_schema: CFDPayloadSchema,
    demo_or_live: str,
    profit_or_loss: float,
    funds_to_use=float,
    crucial_details: str,
):
    lots_to_open, update_profit_or_loss_in_db = get_lots_to_trade_and_profit_or_loss(
        funds_to_use, cfd_strategy_schema, profit_or_loss, crucial_details
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
                    msg = f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] throttled while opening lots [ {lots_to_open} ] response:  {response_json}"
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
                    msg = f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] RISK_CHECK while opening lots [ {lots_to_open} ] response:  {response_json}"
                    logging.warning(msg)
                    logging.info(
                        f"[ {crucial_details} ] calculating lots to open again as available funds are updated"
                    )
                    # funds_to_use = await get_funds_to_use(client, cfd_strategy_schema)

                    (
                        lots_to_open,
                        update_profit_or_loss_in_db,
                    ) = get_lots_to_trade_and_profit_or_loss(
                        0.0, cfd_strategy_schema, profit_or_loss, crucial_details
                    )
                    place_order_attempt += 1
                    await client.__log_out__()
                    await asyncio.sleep(1)
                    continue
                else:
                    logging.error(
                        f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] rejected, deal status: {response_json['dealStatus']}, reason: {response_json['rejectReason']}, status: {response_json['status']}"
                    )
                    return response_json
            elif response_json["dealStatus"] == "ACCEPTED":
                long_or_short = "LONG" if cfd_payload_schema.direction == "buy" else "SHORT"
                msg = f"[ {crucial_details} ] - successfully [ {long_or_short}  {lots_to_open} ] trades."
                logging.info(msg)
            else:
                msg = f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] Error in placing open lots, deal status: {response_json}"
                logging.error(msg)

            if update_profit_or_loss_in_db:
                # update funds balance
                await update_cfd_strategy_funds(
                    cfd_strategy_schema=cfd_strategy_schema,
                    crucial_details=crucial_details,
                    profit_or_loss=update_profit_or_loss_in_db,
                )
            else:
                logging.info(f"[ {crucial_details} ] : No profit or loss to update in db")
            return msg
        except httpx.HTTPStatusError as error:
            response_json = error.response
            status_code, text = response_json.status_code, response_json.text
            if status_code == 429:
                logging.warning(
                    f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] throttled while opening lots [ {lots_to_open} ] {status_code} {text}"
                )
                logging.info(f"[ {crucial_details} ] : attempting again to open lots")
                # too many requests
                place_order_attempt += 1
                await client.__log_out__()
                await asyncio.sleep(2)
            elif status_code in [400, 404]:
                # # if it throws 404 exception saying dealreference not found then try to fetch all positions
                # # and see if order is placed and if not then try it again and if it is placed then skip it
                logging.warning(
                    f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] while opening lots {status_code} {text}"
                )
                await asyncio.sleep(2)
                logging.info(
                    f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] may be lots are opened , so fetching all positions againa and verifying the same"
                )

                _open_order_found = await open_order_found(
                    client=client,
                    cfd_strategy_schema=cfd_strategy_schema,
                    cfd_payload_schema=cfd_payload_schema,
                    lots_size=lots_to_open,
                    crucial_details=crucial_details,
                )

                if _open_order_found:
                    break

                position_found = await find_position(
                    client=client,
                    demo_or_live=demo_or_live,
                    cfd_strategy_schema=cfd_strategy_schema,
                    current_open_lots=lots_to_open,
                    action="open",
                    crucial_details=crucial_details,
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
                        msg = f"[ {crucial_details} ] - successfully [ {long_or_short}  {lots_to_open} ] trades."
                        logging.info(msg)

                        await update_cfd_strategy_funds(
                            cfd_strategy_schema=cfd_strategy_schema,
                            crucial_details=crucial_details,
                            profit_or_loss=profit_or_loss,
                        )
                        # TODO: try to open lots with the profit gained
                        break
                    else:
                        # very rare case where lots are still in current direction.
                        # trying to close them by updating "lots_to_open" to the lots from position response
                        logging.warning(
                            f"[ {crucial_details} ] - lots are still in current [ {response_direction} ] direction. trying to close [ {response_lots} ] lots."
                        )
                        lots_to_open = response_lots
                        place_order_attempt += 1
                        await asyncio.sleep(3)
                else:
                    place_order_attempt += 1
                    await asyncio.sleep(1)
            else:
                msg = f"[ {crucial_details} ] - Error occured while opening lots, Error: {text}"
                logging.error(msg)
                return msg
