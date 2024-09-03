import asyncio
import logging

import httpx
from _decimal import ROUND_DOWN
from _decimal import Decimal
from _decimal import getcontext
from fastapi import HTTPException
from sqlalchemy import update

from app.broker_clients.uk.async_capital import AsyncCapitalClient
from app.database.schemas import CFDStrategyDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.strategy import CFDStrategyPydModel
from app.pydantic_models.strategy import StrategyPydModel
from app.pydantic_models.trade import CFDPayloadPydModel


def get_lots_to_trade_and_profit_or_loss(
    funds_to_use,
    strategy_pyd_model: CFDStrategyPydModel | StrategyPydModel,
    ongoing_profit_or_loss,
    crucial_details: str = None,
):
    def _get_lots_to_trade(strategy_funds_to_trade, strategy_pyd_model):
        # below is the core of this function, do not mendle with it
        # Calculate the quantity that can be traded in the current period
        approx_lots_to_trade = strategy_funds_to_trade * (
            Decimal(strategy_pyd_model.min_quantity)
            / Decimal(strategy_pyd_model.margin_for_min_quantity)
        )

        to_increment = Decimal(strategy_pyd_model.incremental_step_size)
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
        # drawdown_percentage = Decimal(cfd_strategy_pyd_model.max_drawdown) / (
        #     Decimal(cfd_strategy_pyd_model.margin_for_min_quantity)
        # )
        #
        # # Calculate the funds that can be traded in the current period
        # funds_to_trade = (
        #     Decimal(cfd_strategy_pyd_model.funds) + Decimal(ongoing_profit_or_loss)
        # ) / (1 + drawdown_percentage)
        #

        # i think below code  doesn't make any sense as i have seen if available funds are in negative still i can trade in broker_clients,
        # don't know how it works in indian broker_clients like zerodha , keeping it for now
        # if funds_to_use < ongoing_profit_or_loss:
        #     funds_to_trade = Decimal(strategy_pyd_model.funds + (funds_to_use * 0.95))
        #     to_update_profit_or_loss_in_db = funds_to_use
        # else:
        #     funds_to_trade = Decimal(strategy_pyd_model.funds + (ongoing_profit_or_loss * 0.95))
        #     to_update_profit_or_loss_in_db = ongoing_profit_or_loss

        strategy_funds_to_trade = Decimal(
            (strategy_pyd_model.funds + ongoing_profit_or_loss)
            * strategy_pyd_model.funds_usage_percent
        )
        strategy_funds_to_trade = round(strategy_funds_to_trade, 2)
        logging.info(
            f"[ {crucial_details} ] - strategy_funds_to_trade: {strategy_funds_to_trade}"
        )

        if strategy_funds_to_trade < Decimal(strategy_pyd_model.margin_for_min_quantity):
            logging.info(
                f"[ {crucial_details} ] - strategy_funds_to_trade: [ {strategy_funds_to_trade} ] is less than margin for min quantity: {strategy_pyd_model.margin_for_min_quantity}"
            )
            strategy_funds_to_trade = Decimal(strategy_pyd_model.margin_for_min_quantity)

        to_update_profit_or_loss_in_db = ongoing_profit_or_loss
        if not strategy_pyd_model.compounding:
            logging.info(
                f"[ {crucial_details} ] - Compounding is not enabled, so we will trade fixed contracts: [ {strategy_pyd_model.contracts} ]"
            )
            funds_required_for_contracts = Decimal(
                (strategy_pyd_model.margin_for_min_quantity / strategy_pyd_model.min_quantity)
                * strategy_pyd_model.contracts
            )
            available_funds = Decimal(strategy_pyd_model.funds + ongoing_profit_or_loss)
            if funds_required_for_contracts <= available_funds:
                lots_to_trade = strategy_pyd_model.contracts
                logging.info(
                    f"[ {crucial_details} ] - Available Funds: [ {available_funds} ] are more than funds required for contracts: [ {funds_required_for_contracts} ]"
                )
            else:
                lots_to_trade = _get_lots_to_trade(available_funds, strategy_pyd_model)
                logging.info(
                    f"[ {crucial_details} ] - Available Funds: [ {available_funds} ] are less than funds required for contracts: [ {funds_required_for_contracts} ]. So we will trade [ {lots_to_trade} ] contracts"
                )
        else:
            lots_to_trade = _get_lots_to_trade(strategy_funds_to_trade, strategy_pyd_model)
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
    client: AsyncCapitalClient,
    cfd_strategy_pyd_model: CFDStrategyPydModel,
    crucial_details: str,
) -> dict:
    get_all_positions_attempt = 1
    error = None
    while get_all_positions_attempt < 10:
        try:
            # retrieving all positions throws
            # 429 i.e. {"errorCode":"error.too-many.requests"}
            # 401: {"errorCode":"error.invalid.details"},
            # 400: don't know
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
    client: AsyncCapitalClient,
    cfd_strategy_pyd_model: CFDStrategyPydModel,
    crucial_details: str,
) -> tuple[int, int, str | None]:
    direction = None
    profit_or_loss_value = 0
    existing_lot = 0
    positions = await get_all_positions(client, cfd_strategy_pyd_model, crucial_details)
    for position in positions["positions"]:
        if position["market"]["epic"] == cfd_strategy_pyd_model.instrument:
            profit_or_loss_value += position["position"]["upl"]
            existing_lot += position["position"]["size"]
            direction = position["position"]["direction"]

    profit_or_loss_str = "profit" if profit_or_loss_value > 0 else "loss"
    logging.info(
        f"[ {crucial_details} ] - current lots: [ {existing_lot} ] {profit_or_loss_str}: [ {profit_or_loss_value} ], direction: [ {direction} ] to be closed"
    )
    return round(profit_or_loss_value, 2), existing_lot, direction


async def get_funds_to_use(
    client, cfd_strategy_pyd_model: CFDStrategyPydModel, crucial_details: str
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
    *,
    cfd_strategy_pyd_model: CFDStrategyPydModel,
    profit_or_loss: float,
    crucial_details: str,
):
    log_profit_or_loss = "profit" if profit_or_loss > 0 else "loss"

    updated_funds = round(cfd_strategy_pyd_model.funds + profit_or_loss, 2)
    async with Database() as async_session:
        await async_session.execute(
            update(CFDStrategyDBModel)
            .where(CFDStrategyDBModel.id == cfd_strategy_pyd_model.id)
            .values(funds=updated_funds)
        )
        await async_session.commit()
        logging.info(
            f"[ {crucial_details} ] - funds balance [ {cfd_strategy_pyd_model.funds} ] got updated to [ {updated_funds} ] after {log_profit_or_loss}: {profit_or_loss} "
        )


async def open_order_found(
    *,
    client: AsyncCapitalClient,
    cfd_strategy_pyd_model: CFDStrategyPydModel,
    cfd_payload_pyd_model: CFDPayloadPydModel,
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
                instrument == cfd_strategy_pyd_model.instrument
                and direction != cfd_payload_pyd_model.direction
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
    cfd_strategy_pyd_model: CFDStrategyPydModel,
    current_open_lots: float,
    action: str,
    crucial_details: str,
):
    if positions := await get_all_positions(client, cfd_strategy_pyd_model, crucial_details):
        for position in positions["positions"]:
            if position["market"]["epic"] == cfd_strategy_pyd_model.instrument:
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
