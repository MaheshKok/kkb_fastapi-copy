from contextlib import asynccontextmanager

from app.core.config import get_config
from app.database.base import get_async_session_maker
from app.database.base import get_db_url
from app.utils.option_chain import get_option_chain


@asynccontextmanager
async def _get_async_session_maker(config_file):
    config = get_config(config_file)
    async_db_url = get_db_url(config)
    async_session_maker = get_async_session_maker(async_db_url)
    async_session = async_session_maker()

    try:
        yield async_session
        await async_session.commit()
    except Exception as e:
        await async_session.rollback()
        raise e
    finally:
        await async_session.close()


async def get_exit_price_from_option_chain(
    redis_ongoing_trades, symbol, expiry_date, option_type
):
    # reason for using set comprehension, we want the exit_price for all distinct strikes
    strikes = {trade["strike"] for trade in redis_ongoing_trades}
    option_chain = await get_option_chain(symbol, expiry_date, option_type)
    return {strike: option_chain[strike] for strike in strikes}


async def get_future_price(symbol, expiry_date):
    # get future price from redis
    # TODO: compute future price from argument expiry_data

    future_option_chain = await get_option_chain(symbol, expiry_date, is_future=True)
    return float(future_option_chain["FUT"])


async def get_strike_and_exit_price_dict(trade_payload, redis_ongoing_trades) -> dict:
    symbol = trade_payload["symbol"]
    expiry_date = trade_payload["expiry"]
    option_type = trade_payload["option_type"]

    # Reason being trade_payload is an entry trade and we want to close all ongoing trades of opposite option_type
    ongoing_trades_option_type = "PE" if option_type == "CE" else "CE"

    # TODO: Uncomment if i cant send dict as an argument via celery task
    # redis_ongoing_trades_key = f"{trade_payload['strategy_id']} {expiry_date} {'pe' if trade_payload['option_type'] == 'ce' else 'ce'}"

    if broker_id := trade_payload.get("broker_id"):
        print("broker_id", broker_id)
        # close trades in broker and get exit price
        strike_exit_price_dict = {}
    else:
        # get exit price from option chain
        strike_exit_price_dict = await get_exit_price_from_option_chain(
            redis_ongoing_trades, symbol, expiry_date, ongoing_trades_option_type
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
