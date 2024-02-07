import json
import logging
import traceback
from datetime import date
from datetime import datetime
from typing import List
from typing import Optional

from aioredis import Redis
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.utils import get_expiry_dict_from_alice_blue
from app.broker.utils import buy_alice_blue_trades
from app.broker.utils import close_alice_blue_trades
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.utils.constants import REDIS_DATE_FORMAT
from app.utils.constants import OptionType
from app.utils.option_chain import get_option_chain


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def get_exit_price_from_option_chain(
    async_redis_client,
    redis_trade_schema_list,
    expiry_date,
    option_type,
    strategy_schema: StrategySchema,
):
    # reason for using set comprehension, we want the exit_price for all distinct strikes
    strikes = {trade.strike for trade in redis_trade_schema_list}
    option_chain = await get_option_chain(
        async_redis_client=async_redis_client,
        expiry=expiry_date,
        strategy_schema=strategy_schema,
        option_type=option_type,
    )
    return {strike: option_chain[strike] for strike in strikes}


def strip_previous_expiry_dates(expiry_list_date_obj):
    todays_date = datetime.today().date()
    upcoming_expiry_dates = [_date for _date in expiry_list_date_obj if _date >= todays_date]
    return upcoming_expiry_dates


async def get_monthly_expiry_date_from_redis(
    *, async_redis_client: Redis, instrument_type: InstrumentTypeEnum, symbol: str
):
    symbol_expiry_str = await async_redis_client.get(instrument_type)
    symbol_expiry = json.loads(symbol_expiry_str)
    expiry_list_date_obj = [
        datetime.strptime(expiry, "%Y-%m-%d").date() for expiry in symbol_expiry[symbol]
    ]
    expiry_list_date_obj = strip_previous_expiry_dates(expiry_list_date_obj)
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


async def get_monthly_expiry_date_from_alice_blue(*, instrument_type, symbol):
    expiry_dict = await get_expiry_dict_from_alice_blue()
    expiry_list = expiry_dict[instrument_type][symbol]
    expiry_datetime_obj_list = [
        datetime.strptime(expiry, REDIS_DATE_FORMAT).date() for expiry in expiry_list
    ]
    expiry_list_date_obj = strip_previous_expiry_dates(expiry_datetime_obj_list)
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


async def get_future_price_from_redis(
    *,
    async_redis_client: Redis,
    strategy_schema: StrategySchema,
    expiry_date: date,
):
    future_option_chain = await get_option_chain(
        async_redis_client=async_redis_client,
        expiry=expiry_date,
        strategy_schema=strategy_schema,
        is_future=True,
    )

    if not future_option_chain:
        return 0.0

    return float(future_option_chain["FUT"])


async def get_future_price(
    *,
    async_redis_client: Redis,
    strategy_schema: StrategySchema,
    expiry_date: date,
    signal_payload_schema: SignalPayloadSchema,
    async_httpx_client: AsyncClient,
    redis_trade_schema_list: Optional[List[RedisTradeSchema]] = None,
) -> float:
    # fetch future price from alice blue only when
    # strategy_schema.instrument_type == InstrumentTypeEnum.FUTIDX and
    # strategy_schema.broker_id is not None
    # for all the other scenario fetch it from redis
    if strategy_schema.instrument_type == InstrumentTypeEnum.FUTIDX:
        if strategy_schema.broker_id:
            if signal_payload_schema.action == SignalTypeEnum.BUY:
                future_price = await buy_alice_blue_trades(
                    strike=None,
                    signal_payload_schema=signal_payload_schema,
                    async_redis_client=async_redis_client,
                    strategy_schema=strategy_schema,
                    async_httpx_client=async_httpx_client,
                )
                return future_price
            else:
                future_price_dict = await close_alice_blue_trades(
                    redis_trade_schema_list,
                    strategy_schema,
                    async_redis_client,
                    async_httpx_client,
                )
                future_price = future_price_dict[None]
                return future_price

    future_price = await get_future_price_from_redis(
        async_redis_client=async_redis_client,
        strategy_schema=strategy_schema,
        expiry_date=expiry_date,
    )
    return future_price


async def get_strike_and_exit_price_dict(
    *,
    async_redis_client: Redis,
    signal_payload_schema: SignalPayloadSchema,
    redis_trade_schema_list: list[RedisTradeSchema],
    strategy_schema: StrategySchema,
    async_httpx_client: AsyncClient,
    expiry_date: date,
) -> dict:
    # Reason being trade_payload is an entry trade and we want to close all ongoing trades of opposite option_type
    ongoing_trades_option_type = (
        OptionType.PE if signal_payload_schema.option_type == OptionType.CE else OptionType.CE
    )

    if strategy_schema.broker_id:
        strike_exit_price_dict = await close_alice_blue_trades(
            redis_trade_schema_list, strategy_schema, async_redis_client, async_httpx_client
        )
    else:
        # get exit price from option chain
        strike_exit_price_dict = await get_exit_price_from_option_chain(
            async_redis_client=async_redis_client,
            redis_trade_schema_list=redis_trade_schema_list,
            expiry_date=expiry_date,
            option_type=ongoing_trades_option_type,
            strategy_schema=strategy_schema,
        )

    return strike_exit_price_dict


async def get_strike_and_entry_price_from_option_chain(
    *, option_chain, signal_payload_schema: SignalPayloadSchema, premium: float
):
    strike = signal_payload_schema.strike
    premium = premium
    future_price = signal_payload_schema.future_entry_price_received

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
    strategy_schema: StrategySchema,
    signal_payload_schema: SignalPayloadSchema,
    async_redis_client: Redis,
    async_httpx_client: AsyncClient,
    crucial_details: str,
) -> tuple[float, float]:
    strike, premium = await get_strike_and_entry_price_from_option_chain(
        option_chain=option_chain,
        signal_payload_schema=signal_payload_schema,
        premium=strategy_schema.premium,
    )

    if strategy_schema.broker_id:
        try:
            entry_price = await buy_alice_blue_trades(
                strike=strike,
                signal_payload_schema=signal_payload_schema,
                strategy_schema=strategy_schema,
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


def set_quantity(
    *,
    signal_payload_schema: SignalPayloadSchema,
    quantity: float,
    strategy_schema: StrategySchema,
) -> None:
    if strategy_schema.instrument_type == InstrumentTypeEnum.OPTIDX:
        if strategy_schema.position == PositionEnum.LONG:
            signal_payload_schema.quantity = quantity
        else:
            signal_payload_schema.quantity = -quantity
    else:
        # this is for futures
        if signal_payload_schema.action == SignalTypeEnum.BUY:
            signal_payload_schema.quantity = quantity
        else:
            signal_payload_schema.quantity = -quantity
