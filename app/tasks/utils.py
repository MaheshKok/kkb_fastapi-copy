import logging
import traceback
from datetime import datetime

from aioredis import Redis
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.utils import get_expiry_list
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.services.broker.utils import buy_alice_blue_trades
from app.services.broker.utils import close_alice_blue_trades
from app.utils.constants import OptionType
from app.utils.option_chain import get_option_chain


async def get_exit_price_from_option_chain(
    async_redis_client,
    redis_trade_schema_list,
    symbol,
    expiry_date,
    option_type,
    strategy_schema: StrategySchema,
):
    # reason for using set comprehension, we want the exit_price for all distinct strikes
    strikes = {trade.strike for trade in redis_trade_schema_list}
    option_chain = await get_option_chain(
        async_redis_client=async_redis_client,
        symbol=symbol,
        expiry=expiry_date,
        strategy_schema=strategy_schema,
        option_type=option_type,
    )
    return {strike: option_chain[strike] for strike in strikes}


async def get_monthly_expiry_date(async_redis_client):
    """
    if expiry_list = ["06 Jul 2023", "13 Jul 2023", "20 Jul 2023", "27 Jul 2023", "03 Aug 2023", "31 Aug 2023", "28 Sep 2023", "28 Dec 2023", "31 Dec 2026", "24 Jun 2027", "30 Dec 2027"]
    and today is 27th June then we have to find july months expiry

    logic:
        start iterating over expiry list till second last expiry_date
        now check if the current item expiry date month is less then next expiry_date in list

    if today is june then current month will be set to july month and thats why logic will work

    """

    expiry_dates = await get_expiry_list(async_redis_client)
    monthly_expiry_date = None

    current_month = datetime.now().date().month
    if current_month < expiry_dates[0].month:
        current_month = current_month + 1

    for index, expiry_date in enumerate(expiry_dates[:-1]):
        if current_month < expiry_dates[index + 1].month:
            monthly_expiry_date = expiry_date
            break

    return monthly_expiry_date


async def get_future_price(async_redis_client, symbol, strategy_schema):
    monthly_expiry_date = await get_monthly_expiry_date(async_redis_client)

    # I hope this never happens
    if not monthly_expiry_date:
        return 0.0

    future_option_chain = await get_option_chain(
        async_redis_client=async_redis_client,
        symbol=symbol,
        expiry=monthly_expiry_date,
        strategy_schema=strategy_schema,
        is_future=True,
    )

    if not future_option_chain:
        return 0.0

    return float(future_option_chain["FUT"])


async def get_strike_and_exit_price_dict(
    *,
    async_redis_client: Redis,
    signal_payload_schema: SignalPayloadSchema,
    redis_trade_schema_list: list[RedisTradeSchema],
    strategy_schema: StrategySchema,
    async_httpx_client: AsyncClient,
) -> dict:
    # Reason being trade_payload is an entry trade and we want to close all ongoing trades of opposite option_type
    ongoing_trades_option_type = (
        OptionType.PE if signal_payload_schema.option_type == OptionType.CE else OptionType.CE
    )

    if strategy_schema.broker_id:
        # TODO: close trades in broker and get exit price
        strike_exit_price_dict = await close_alice_blue_trades(
            redis_trade_schema_list, strategy_schema, async_redis_client, async_httpx_client
        )
    else:
        # get exit price from option chain
        strike_exit_price_dict = await get_exit_price_from_option_chain(
            async_redis_client=async_redis_client,
            redis_trade_schema_list=redis_trade_schema_list,
            symbol=signal_payload_schema.symbol,
            expiry_date=signal_payload_schema.expiry,
            option_type=ongoing_trades_option_type,
            strategy_schema=strategy_schema,
        )

    return strike_exit_price_dict


async def get_strike_and_entry_price_from_option_chain(
    option_chain, signal_payload_schema: SignalPayloadSchema
):
    strike = signal_payload_schema.strike
    premium = signal_payload_schema.premium
    future_price = signal_payload_schema.future_entry_price_received

    # use bisect to find the strike and its price from option chain
    if strike:
        if premium := option_chain.get(strike):
            return strike, premium
        # even if strike is not present in option chain then the closest strike will be fetched
        # convert it to float for comparison
        strike = float(strike)
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
):
    strike, premium = await get_strike_and_entry_price_from_option_chain(
        option_chain=option_chain, signal_payload_schema=signal_payload_schema
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
            return strike, entry_price
        except BaseException as e:
            logging.error(f"error while buying trade {e}")
            traceback.print_exc()
            raise HTTPException(status_code=e.status_code, detail=e.detail)

    return strike, premium
