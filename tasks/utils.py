from datetime import datetime

from app.api.utils import get_expiry_list
from app.schemas.trade import SignalPayloadSchema
from app.utils.option_chain import get_option_chain


async def get_exit_price_from_option_chain(
    async_redis_client, redis_trade_schema_list, symbol, expiry_date, option_type
):
    # reason for using set comprehension, we want the exit_price for all distinct strikes
    strikes = {trade.strike for trade in redis_trade_schema_list}
    option_chain = await get_option_chain(async_redis_client, symbol, expiry_date, option_type)
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


async def get_future_price(async_redis_client, symbol):
    monthly_expiry_date = await get_monthly_expiry_date(async_redis_client)

    # I hope this never happens
    if not monthly_expiry_date:
        return 0.0

    future_option_chain = await get_option_chain(
        async_redis_client, symbol, monthly_expiry_date, is_future=True
    )
    return float(future_option_chain["FUT"])


async def get_strike_and_exit_price_dict(
    async_redis_client,
    signal_payload_schema: SignalPayloadSchema,
    redis_trade_schema_list,
    strategy_schema,
) -> dict:
    # Reason being trade_payload is an entry trade and we want to close all ongoing trades of opposite option_type
    ongoing_trades_option_type = "PE" if signal_payload_schema.option_type == "CE" else "CE"

    # TODO: Uncomment if i cant send dict as an argument via celery task
    # redis_ongoing_trades_key = f"{trade_payload['strategy_id']} {expiry_date} {'pe' if trade_payload['option_type'] == 'ce' else 'ce'}"

    if strategy_schema.broker_id:
        print("broker_id", strategy_schema.broker_id)
        # TODO: close trades in broker and get exit price
        strike_exit_price_dict = {}
    else:
        # get exit price from option chain
        strike_exit_price_dict = await get_exit_price_from_option_chain(
            async_redis_client,
            redis_trade_schema_list,
            signal_payload_schema.symbol,
            signal_payload_schema.expiry,
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
