import json
import logging
from datetime import date

import aioredis
from fastapi import HTTPException

from app.api.trade.indian_fno.utils import get_angel_one_futures_trading_symbol
from app.api.trade.indian_fno.utils import get_angel_one_options_trading_symbol
from app.pydantic_models.angel_one import InstrumentPydanticModel
from app.utils.constants import OptionType


def generate_angel_one_complete_symbol(
    *,
    symbol: str,
    expiry_date: date,
    strike: int = None,
    option_type: OptionType = None,
    is_fut: bool = False,
):
    if is_fut:
        return get_angel_one_futures_trading_symbol(
            symbol=symbol,
            expiry_date=expiry_date,
        )
    return get_angel_one_options_trading_symbol(
        symbol=symbol,
        expiry_date=expiry_date,
        strike=strike,
        option_type=option_type.value,
    )


async def get_angel_one_instrument_details(
    *,
    async_redis_client: aioredis.Redis,
    symbol: str,
    expiry_date: date,
    strike: int = None,
    option_type: OptionType = None,
    is_fut=False,
) -> InstrumentPydanticModel:
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
    logging.info(f"[ {angel_one_complete_symbol} ] - getting instrument token")

    instrument_details = await async_redis_client.get(angel_one_complete_symbol)

    if not instrument_details:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument detail: {angel_one_complete_symbol} not found in redis",
        )

    instrument_details = json.loads(instrument_details)
    return InstrumentPydanticModel(**instrument_details)
