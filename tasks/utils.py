from app.schemas.trade import CeleryTradeSchema
from app.utils.option_chain import get_option_chain


async def get_exit_price_from_option_chain(
    async_redis, redis_ongoing_trades, symbol, expiry_date, option_type
):
    # reason for using set comprehension, we want the exit_price for all distinct strikes
    strikes = {trade["strike"] for trade in redis_ongoing_trades}
    option_chain = await get_option_chain(async_redis, symbol, expiry_date, option_type)
    return {strike: option_chain[strike] for strike in strikes}


async def get_future_price(async_redis, symbol, expiry_date):
    # get future price from redis
    # TODO: compute future price from argument expiry_data

    future_option_chain = await get_option_chain(async_redis, symbol, expiry_date, is_future=True)
    return float(future_option_chain["FUT"])


async def get_strike_and_exit_price_dict(
    async_redis, celery_trade_schema: CeleryTradeSchema, redis_ongoing_trades
) -> dict:
    # Reason being trade_payload is an entry trade and we want to close all ongoing trades of opposite option_type
    ongoing_trades_option_type = "PE" if celery_trade_schema.option_type == "CE" else "CE"

    # TODO: Uncomment if i cant send dict as an argument via celery task
    # redis_ongoing_trades_key = f"{trade_payload['strategy_id']} {expiry_date} {'pe' if trade_payload['option_type'] == 'ce' else 'ce'}"

    if celery_trade_schema.broker_id:
        print("broker_id", celery_trade_schema.broker_id)
        # TODO: close trades in broker and get exit price
        strike_exit_price_dict = {}
    else:
        # get exit price from option chain
        strike_exit_price_dict = await get_exit_price_from_option_chain(
            async_redis,
            redis_ongoing_trades,
            celery_trade_schema.symbol,
            celery_trade_schema.expiry,
            ongoing_trades_option_type,
        )

    return strike_exit_price_dict


def get_strike_and_entry_price(option_chain, strike=None, premium=None, future_price=None):
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

    raise Exception("Either premium or strike or future_price should be provided")
