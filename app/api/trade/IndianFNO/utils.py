import io
import json
import logging
import traceback
from datetime import date
from datetime import datetime
from typing import List
from typing import Optional

import aioredis
import httpx
import pandas as pd
from _decimal import ROUND_DOWN
from _decimal import Decimal
from _decimal import getcontext
from aioredis import Redis
from fastapi import HTTPException
from httpx import AsyncClient
from starlette import status

from app.broker.AsyncAngelOne import AsyncAngelOneClient
from app.broker.utils import buy_alice_blue_trades
from app.broker.utils import close_alice_blue_trades
from app.pydantic_models.broker import AngelOneInstrumentPydanticModel
from app.pydantic_models.enums import InstrumentTypeEnum
from app.pydantic_models.enums import OptionTypeEnum
from app.pydantic_models.enums import PositionEnum
from app.pydantic_models.enums import ProductTypeEnum
from app.pydantic_models.enums import SignalTypeEnum
from app.pydantic_models.strategy import StrategyPydanticModel
from app.pydantic_models.trade import RedisTradePydanticModel
from app.pydantic_models.trade import SignalPydanticModel
from app.utils.constants import ANGELONE_EXPIRY_DATE_FORMAT
from app.utils.constants import FUT
from app.utils.constants import REDIS_DATE_FORMAT
from app.utils.option_chain import get_option_chain


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def get_exit_price_from_option_chain(
    async_redis_client,
    redis_trade_pydantic_model_list,
    expiry_date,
    strategy_pydantic_model: StrategyPydanticModel,
):
    option_type = redis_trade_pydantic_model_list[0].option_type
    # reason for using set comprehension, we want the exit_price for all distinct strikes
    strikes = {trade.strike for trade in redis_trade_pydantic_model_list}
    option_chain = await get_option_chain(
        async_redis_client=async_redis_client,
        expiry=expiry_date,
        strategy_pydantic_model=strategy_pydantic_model,
        option_type=option_type,
    )
    return {strike: option_chain[strike] for strike in strikes}


def strip_previous_expiry_dates(expiry_list_date_obj):
    todays_date = datetime.today().date()
    upcoming_expiry_dates = [_date for _date in expiry_list_date_obj if _date >= todays_date]
    return upcoming_expiry_dates


def get_current_and_next_expiry_from_expiry_list(expiry_list_date_obj):
    current_month_expiry = expiry_list_date_obj[0]
    next_month_expiry = None
    is_today_months_expiry = False

    for i in range(1, len(expiry_list_date_obj)):
        if (
            expiry_list_date_obj[i].month != expiry_list_date_obj[i - 1].month
        ):  # If a change of month is detected in the list
            # Save the last date of the previous month
            if expiry_list_date_obj[i - 1].month == datetime.now().month:  # adjust this as needed
                current_month_expiry = expiry_list_date_obj[i - 1]
                if current_month_expiry == datetime.now().date():
                    is_today_months_expiry = True
            elif expiry_list_date_obj[i - 1].month == ((datetime.now().month % 12) + 1):
                next_month_expiry = expiry_list_date_obj[i - 1]
        # Catch the last date of the next month, in case the loop finishes
        elif i == len(expiry_list_date_obj) - 1 and expiry_list_date_obj[i].month == (
            (datetime.now().month % 12) + 1
        ):
            next_month_expiry = expiry_list_date_obj[i]

    return current_month_expiry, next_month_expiry, is_today_months_expiry


async def get_monthly_expiry_date_from_redis(
    *, async_redis_client: Redis, instrument_type: InstrumentTypeEnum, symbol: str
):
    expiry_dict_json = await async_redis_client.get(instrument_type)
    expiry_list = json.loads(expiry_dict_json)[symbol]
    expiry_datetime_obj_list = [
        datetime.strptime(expiry, REDIS_DATE_FORMAT).date() for expiry in expiry_list
    ]
    expiry_list_date_obj = strip_previous_expiry_dates(expiry_datetime_obj_list)
    return get_current_and_next_expiry_from_expiry_list(expiry_list_date_obj)


async def get_monthly_expiry_date_from_alice_blue(*, instrument_type, symbol):
    expiry_dict = await get_expiry_dict_from_alice_blue()
    expiry_list = expiry_dict[instrument_type][symbol]
    expiry_datetime_obj_list = [
        datetime.strptime(expiry, REDIS_DATE_FORMAT).date() for expiry in expiry_list
    ]
    expiry_list_date_obj = strip_previous_expiry_dates(expiry_datetime_obj_list)
    return get_current_and_next_expiry_from_expiry_list(expiry_list_date_obj)


async def get_future_price_from_redis(
    *,
    async_redis_client: Redis,
    strategy_pydantic_model: StrategyPydanticModel,
    expiry_date: date,
):
    future_option_chain = await get_option_chain(
        async_redis_client=async_redis_client,
        expiry=expiry_date,
        strategy_pydantic_model=strategy_pydantic_model,
        is_future=True,
    )

    if not future_option_chain:
        return 0.0

    return float(future_option_chain["FUT"])


async def get_future_price(
    *,
    async_redis_client: Redis,
    strategy_pydantic_model: StrategyPydanticModel,
    expiry_date: date,
    signal_pydantic_model: SignalPydanticModel,
    async_httpx_client: AsyncClient,
    redis_trade_pydantic_model_list: Optional[List[RedisTradePydanticModel]] = None,
) -> float:
    # fetch future price from alice blue only when
    # strategy_pydantic_model.instrument_type == InstrumentTypeEnum.FUTIDX and
    # strategy_pydantic_model.broker_id is not None
    # for all the other scenario fetch it from redis
    if strategy_pydantic_model.instrument_type == InstrumentTypeEnum.FUTIDX:
        if strategy_pydantic_model.broker_id:
            if signal_pydantic_model.action == SignalTypeEnum.BUY:
                future_price = await buy_alice_blue_trades(
                    strike=None,
                    signal_pydantic_model=signal_pydantic_model,
                    async_redis_client=async_redis_client,
                    strategy_pydantic_model=strategy_pydantic_model,
                    async_httpx_client=async_httpx_client,
                )
                return future_price
            else:
                future_price_dict = await close_alice_blue_trades(
                    redis_trade_pydantic_model_list,
                    strategy_pydantic_model,
                    async_redis_client,
                    async_httpx_client,
                )
                future_price = future_price_dict[None]
                return future_price

    future_price = await get_future_price_from_redis(
        async_redis_client=async_redis_client,
        strategy_pydantic_model=strategy_pydantic_model,
        expiry_date=expiry_date,
    )
    return future_price


async def get_strike_and_exit_price_dict(
    *,
    async_redis_client: Redis,
    redis_trade_pydantic_model_list: list[RedisTradePydanticModel],
    strategy_pydantic_model: StrategyPydanticModel,
    async_httpx_client: AsyncClient,
    expiry_date: date,
) -> dict:
    if strategy_pydantic_model.broker_id:
        strike_exit_price_dict = await close_alice_blue_trades(
            redis_trade_pydantic_model_list,
            strategy_pydantic_model,
            async_redis_client,
            async_httpx_client,
        )
    else:
        # get exit price from option chain
        strike_exit_price_dict = await get_exit_price_from_option_chain(
            async_redis_client=async_redis_client,
            redis_trade_pydantic_model_list=redis_trade_pydantic_model_list,
            expiry_date=expiry_date,
            strategy_pydantic_model=strategy_pydantic_model,
        )

    return strike_exit_price_dict


async def get_strike_and_entry_price_from_option_chain(
    *, option_chain, signal_pydantic_model: SignalPydanticModel, premium: float
):
    strike = signal_pydantic_model.strike
    premium = premium
    future_price = signal_pydantic_model.future_entry_price_received

    # use bisect to find the strike and its price from option chain
    if strike:
        if premium := option_chain.get(strike):
            return strike, premium
        # even if strike is not present in option chain then the closest strike will be fetched
        # convert it to float for comparison
        for option_strike, option_strike_premium in option_chain.items():
            if option_strike_premium != 0.0 and option_strike <= strike:
                return strike, option_strike_premium

    elif premium:
        # get the strike and its price which is just less than the premium
        for strike, strike_premium in option_chain.items():
            if strike_premium != 0.0 and strike_premium <= premium:
                return strike, strike_premium

    elif future_price:
        # TODO: to fetch the strike based on volume and open interest, add more data to option chain
        pass
    else:
        raise Exception("Either premium or strike or future_price should be provided")


async def get_strike_and_entry_price(
    *,
    option_chain,
    strategy_pydantic_model: StrategyPydanticModel,
    signal_pydantic_model: SignalPydanticModel,
    async_redis_client: Redis,
    async_httpx_client: AsyncClient,
    crucial_details: str,
) -> tuple[float, float]:
    strike, premium = await get_strike_and_entry_price_from_option_chain(
        option_chain=option_chain,
        signal_pydantic_model=signal_pydantic_model,
        premium=strategy_pydantic_model.premium,
    )

    if strategy_pydantic_model.broker_id:
        try:
            entry_price = await buy_alice_blue_trades(
                strike=strike,
                signal_pydantic_model=signal_pydantic_model,
                strategy_pydantic_model=strategy_pydantic_model,
                async_redis_client=async_redis_client,
                async_httpx_client=async_httpx_client,
            )
            logging.info(f"[ {crucial_details} ] - entry_price: {entry_price} from alice blue")
            return strike, entry_price
        except HTTPException as e:
            logging.error(f"[ {crucial_details} ] - error while buying trade {e}")
            traceback.print_exc()
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        except BaseException as e:
            logging.error(f"[ {crucial_details} ] - error while buying trade {e}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=json.dumps(e))

    logging.info(f"[ {crucial_details} ] - entry_price: {premium} from redis option chain")
    return strike, premium


async def get_expiry_dict_from_alice_blue():
    api = "https://v2api.aliceblueonline.com/restpy/static/contract_master/NFO.csv"

    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(api)
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
    *, async_redis_client: aioredis.Redis, instrument_type: InstrumentTypeEnum, symbol: str
):
    todays_date = datetime.now().date()

    is_today_expiry = False
    current_expiry_date = None
    next_expiry_date = None
    expiry_list = await get_expiry_list_from_redis(async_redis_client, instrument_type, symbol)

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
            next_expiry_date = expiry_list[index + 1]
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


def set_option_type(
    strategy_pydantic_model: StrategyPydanticModel, payload: SignalPydanticModel
) -> None:
    # this is to prevent setting option type on future strategy, it acts as double protection
    if strategy_pydantic_model.instrument_type == InstrumentTypeEnum.FUTIDX:
        return

    # set OptionTypeEnum base strategy's position column and signal's action.
    strategy_position_trade = {
        PositionEnum.LONG: {
            SignalTypeEnum.BUY: OptionTypeEnum.CE,
            SignalTypeEnum.SELL: OptionTypeEnum.PE,
        },
        PositionEnum.SHORT: {
            SignalTypeEnum.BUY: OptionTypeEnum.PE,
            SignalTypeEnum.SELL: OptionTypeEnum.CE,
        },
    }

    opposite_trade = {OptionTypeEnum.CE: OptionTypeEnum.PE, OptionTypeEnum.PE: OptionTypeEnum.CE}

    position_based_trade = strategy_position_trade.get(strategy_pydantic_model.position)
    payload.option_type = position_based_trade.get(payload.action) or opposite_trade.get(
        payload.option_type
    )


def get_opposite_trade_option_type(strategy_position, signal_action) -> OptionTypeEnum:
    if strategy_position == PositionEnum.LONG:
        if signal_action == SignalTypeEnum.BUY:
            opposite_trade_option_type = OptionTypeEnum.PE
        else:
            opposite_trade_option_type = OptionTypeEnum.CE
    else:
        if signal_action == SignalTypeEnum.BUY:
            opposite_trade_option_type = OptionTypeEnum.CE
        else:
            opposite_trade_option_type = OptionTypeEnum.PE

    return opposite_trade_option_type


def set_quantity(
    strategy_pydantic_model: StrategyPydanticModel,
    signal_pydantic_model: SignalPydanticModel,
    lots_to_open: int,
) -> None:
    if strategy_pydantic_model.instrument_type == InstrumentTypeEnum.OPTIDX:
        if strategy_pydantic_model.position == PositionEnum.LONG:
            signal_pydantic_model.quantity = lots_to_open
        else:
            signal_pydantic_model.quantity = -lots_to_open
    else:
        if signal_pydantic_model.action == SignalTypeEnum.BUY:
            signal_pydantic_model.quantity = lots_to_open
        else:
            signal_pydantic_model.quantity = -lots_to_open


def get_lots_to_open(
    strategy_pydantic_model: StrategyPydanticModel,
    ongoing_profit_or_loss,
    margin_for_min_quantity: float,
    crucial_details: str = None,
):
    def _get_lots_to_trade(strategy_funds_to_trade, strategy_pydantic_model):
        # below is the core of this function, do not mendle with it
        # Calculate the quantity that can be traded in the current period
        approx_lots_to_trade = strategy_funds_to_trade * (
            Decimal(strategy_pydantic_model.min_quantity) / Decimal(margin_for_min_quantity)
        )

        to_increment = Decimal(strategy_pydantic_model.incremental_step_size)
        closest_lots_to_trade = (approx_lots_to_trade // to_increment) * to_increment

        while closest_lots_to_trade + to_increment <= approx_lots_to_trade:
            closest_lots_to_trade += to_increment

        if closest_lots_to_trade + to_increment == approx_lots_to_trade:
            _lots_to_trade = closest_lots_to_trade + to_increment
        else:
            _lots_to_trade = closest_lots_to_trade

        # Add rounding here and Convert the result back to a float for consistency with your existing code
        _lots_to_trade = float(_lots_to_trade.quantize(Decimal("0.01"), rounding=ROUND_DOWN))
        return _lots_to_trade

    # TODO: if funds reach below mranage_for_min_quantity, then we will not trade , handle it
    getcontext().prec = 28  # Set a high precision
    try:
        total_available_funds = strategy_pydantic_model.funds + ongoing_profit_or_loss
        if total_available_funds < margin_for_min_quantity:
            msg = f"[ {crucial_details} ] - total available funds: [ {total_available_funds} ] to trade are less than margin for min quantity: {margin_for_min_quantity}"
            logging.error(msg)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        available_funds = Decimal(
            total_available_funds * strategy_pydantic_model.funds_usage_percent
        )
        available_funds = round(available_funds, 2)
        logging.info(f"[ {crucial_details} ] - available funds: {available_funds}")

        if available_funds < Decimal(margin_for_min_quantity):
            # if funds available are less than margin_for_min_quantity, then we will use margin_for_min_quantity
            """
            Example:
            total available funds = 5Lakh and if funds_usage_percent is 10%
            then available funds = 50K and suppose margin_for_min_quantity = 1Lakh
            then we will trade with 1Lakh and not 5Lakh
            """
            logging.info(
                f"[ {crucial_details} ] - Available Funds: [ {available_funds} ] are less than margin for min quantity: [ {margin_for_min_quantity} ]"
            )
            logging.info(
                f"[ {crucial_details} ] - lots to open [ {strategy_pydantic_model.min_quantity} ]"
            )
            return strategy_pydantic_model.min_quantity

        if not strategy_pydantic_model.compounding:
            logging.info(
                f"[ {crucial_details} ] - Compounding is not enabled, so we will trade fixed contracts: [ {strategy_pydantic_model.contracts} ]"
            )
            funds_required_for_fixed_contracts = Decimal(
                (margin_for_min_quantity / strategy_pydantic_model.min_quantity)
                * strategy_pydantic_model.contracts
            )

            if available_funds >= funds_required_for_fixed_contracts:
                lots_to_trade = strategy_pydantic_model.contracts
                logging.info(
                    f"[ {crucial_details} ] - Available Funds: [ {available_funds} ] are more than funds required for contracts: [ {funds_required_for_fixed_contracts} ]"
                )
            else:
                lots_to_trade = _get_lots_to_trade(available_funds, strategy_pydantic_model)
                logging.info(
                    f"[ {crucial_details} ] - Available Funds: [ {available_funds} ] are less than funds required for contracts: [ {funds_required_for_fixed_contracts} ]. So we will trade [ {lots_to_trade} ] contracts"
                )
        else:
            lots_to_trade = _get_lots_to_trade(available_funds, strategy_pydantic_model)
            logging.info(
                f"[ {crucial_details} ] - Compounding is enabled so we can trade [ {lots_to_trade} ] contracts in [ {total_available_funds} ] funds"
            )

        logging.info(f"[ {crucial_details} ] - lots to open [ {lots_to_trade} ]")
        return lots_to_trade

    except ZeroDivisionError:
        raise HTTPException(
            status_code=400, detail="Division by zero error in trade quantity calculation"
        )


async def get_margin_required(
    *,
    client: AsyncAngelOneClient,
    price: float,
    async_redis_client: Redis,
    angel_one_trading_symbol: str,
    signal_type: SignalTypeEnum,
    strategy_pydantic_model: StrategyPydanticModel,
    crucial_details: str,
):
    instrument_json = await async_redis_client.get(angel_one_trading_symbol)
    instrument = json.loads(instrument_json)
    instrument_pydantic_model = AngelOneInstrumentPydanticModel(**instrument)

    # exchange = NSE, BSE, NFO, CDS, MCX, NCDEX and BFO
    # product_type = CARRYFORWARD, INTRADAY, DELIVERY, MARGIN, BO, and CO.
    #  tradeType = BUY or SELL
    if strategy_pydantic_model.instrument_type == InstrumentTypeEnum.OPTIDX:
        trade_type = (
            SignalTypeEnum.BUY
            if strategy_pydantic_model.position == PositionEnum.LONG
            else SignalTypeEnum.SELL
        )
    else:
        trade_type = signal_type

    params = {
        "positions": [
            {
                "exchange": instrument_pydantic_model.exch_seg,
                "qty": instrument_pydantic_model.lotsize,
                "price": price,
                "productType": ProductTypeEnum.CARRYFORWARD,
                "token": instrument_pydantic_model.token,
                "tradeType": trade_type.upper(),
            }
        ]
    }
    margin_api_response = await client.get_margin_api(params=params)
    if margin_api_response["message"] == "SUCCESS":
        return margin_api_response["data"]["totalMarginRequired"]
    logging.info(
        f"[ {crucial_details} ] - margin required to {trade_type.upper()} lots: [ {instrument_pydantic_model.lotsize} ] is {strategy_pydantic_model.margin_for_min_quantity}"
    )
    return strategy_pydantic_model.margin_for_min_quantity


def get_angel_one_options_trading_symbol(
    symbol: str, expiry_date: date, strike: int, option_type: OptionTypeEnum
) -> str:
    return f"{symbol}{(expiry_date.strftime(ANGELONE_EXPIRY_DATE_FORMAT)).upper()}{strike}{option_type}"


def get_angel_one_futures_trading_symbol(symbol: str, expiry_date: date) -> str:
    return f"{symbol}{(expiry_date.strftime(ANGELONE_EXPIRY_DATE_FORMAT)).upper()}{FUT}"
