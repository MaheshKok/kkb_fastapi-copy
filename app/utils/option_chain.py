import logging

from app.schemas.enums import InstrumentTypeEnum
from app.schemas.strategy import StrategySchema
from app.utils.constants import OptionType


async def get_option_chain(
    *,
    async_redis_client,
    expiry,
    strategy_schema: StrategySchema,
    option_type=None,
    is_future=False,
):
    if is_future and option_type:
        raise ValueError("Futures dont have option_type")

    future_or_option_type = "FUT" if is_future else option_type
    key = f"{strategy_schema.symbol} {expiry} {future_or_option_type}"
    option_chain = await async_redis_client.hgetall(key)
    if option_chain:
        if option_type == OptionType.CE:
            option_chain = {
                float(strike): float(ltp)
                for strike, ltp in sorted(option_chain.items(), key=lambda item: float(item[0]))
            }
            return option_chain
        elif option_type == OptionType.PE:
            option_chain = {
                float(strike): float(ltp)
                for strike, ltp in sorted(
                    option_chain.items(), key=lambda item: float(item[0]), reverse=True
                )
            }
            return option_chain
        else:
            return option_chain

    if strategy_schema.instrument_type == InstrumentTypeEnum.FUTIDX:
        raise Exception(
            f"Option chain data for: [{strategy_schema.symbol} {expiry} {future_or_option_type}] NOT found in redis"
        )
    else:
        logging.error(
            f"Option chain data for: [{strategy_schema.symbol} {expiry} {future_or_option_type}] NOT found in redis"
        )
