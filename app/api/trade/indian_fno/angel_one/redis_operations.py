import json
import logging
from datetime import date

import aioredis
from fastapi import HTTPException

from app.api.trade.indian_fno.utils import get_angel_one_futures_trading_symbol
from app.api.trade.indian_fno.utils import get_angel_one_options_trading_symbol
from app.pydantic_models.angel_one import InstrumentPydModel
from app.pydantic_models.enums import OptionTypeEnum


def generate_angel_one_complete_symbol(
    *,
    symbol: str,
    expiry_date: date,
    strike: int = None,
    option_type: OptionTypeEnum = None,
    is_fut: bool = False,
):
    if is_fut and not option_type:
        return get_angel_one_futures_trading_symbol(
            symbol=symbol,
            expiry_date=expiry_date,
        )

    if option_type and not is_fut:
        return get_angel_one_options_trading_symbol(
            symbol=symbol,
            expiry_date=expiry_date,
            strike=strike,
            option_type=option_type.value,
        )

    if option_type and is_fut:
        raise Exception("Cannot have both is_fut and option_type")


async def get_angel_one_instrument_details(
    *,
    crucial_details: str,
    async_redis_client: aioredis.Redis,
    symbol: str,
    expiry_date: date,
    strike: int = None,
    option_type: OptionTypeEnum = None,
    is_fut=False,
) -> InstrumentPydModel:
    """
    Complete Symbol is of the format:
    'BANKNIFTY31JUL2449400PE' or 'BANKNIFTY31JUL24FUT'
    instrument_details:
        {
            'exch_seg': 'NFO',
            'expiry': '29MAY2024',
            'instrumenttype': 'OPTIDX',
            'lotsize': '15',
            'name': 'BANKNIFTY',
            'strike': '4550000.0000000',
            'symbol': 'BANKNIFTY29MAY2445500CE',
            'tick_size': '5.000000',
            'token': '56584'
        }
    """

    if not is_fut and not (strike and option_type):
        raise Exception("Both is_fut and strike and option_type cannot be None")

    angel_one_complete_symbol = generate_angel_one_complete_symbol(
        symbol=symbol,
        expiry_date=expiry_date,
        strike=strike,
        option_type=option_type,
        is_fut=is_fut,
    )
    logging.info(f"[ {crucial_details} ] - getting instrument token")

    instrument_details = await async_redis_client.get(angel_one_complete_symbol)
    if not instrument_details:
        raise HTTPException(
            status_code=404,
            detail=f"[ {crucial_details} ] - Instrument detail: [ {angel_one_complete_symbol} ] not found in redis",
        )

    instrument_details = json.loads(instrument_details)
    logging.info(
        f"[ {crucial_details} ] - instrument details for: [ {angel_one_complete_symbol} ] found in redis"
    )
    return InstrumentPydModel(**instrument_details)
