import logging
from datetime import datetime

from app.api.utils import get_expiry_list
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.strategy import StrategySchema


async def get_option_chain(
    *,
    async_redis_client,
    symbol,
    expiry,
    strategy_schema: StrategySchema,
    option_type=None,
    is_future=False,
):
    if is_future and option_type:
        raise ValueError("Futures dont have option_type")

    if is_future:
        current_month_number = datetime.now().date().month
        expiry_list = await get_expiry_list(async_redis_client)
        for _, expiry_date in enumerate(expiry_list):
            if expiry_date.month > current_month_number:
                break
            expiry = expiry_date

    future_or_option_type = "FUT" if is_future else option_type
    option_chain = await async_redis_client.hgetall(f"{symbol} {expiry} {future_or_option_type}")
    if option_chain:
        if option_type == "CE":
            return dict(
                sorted([(float(key), float(value)) for key, value in option_chain.items()])
            )
        elif option_type == "PE":
            return dict(
                sorted(
                    [(float(key), float(value)) for key, value in option_chain.items()],
                    reverse=True,
                )
            )
        else:
            return option_chain

    if strategy_schema.instrument_type == InstrumentTypeEnum.FUTIDX:
        raise Exception(
            f"Option chain data for: [{symbol} {expiry} {future_or_option_type}] NOT found in redis"
        )
    else:
        logging.error(
            f"Option chain data for: [{symbol} {expiry} {future_or_option_type}] NOT found in redis"
        )
