from datetime import datetime
from functools import lru_cache

from app.extensions.redis_cache import redis
from app.utils.constants import EDELWEISS_DATE_FORMAT
from app.utils.constants import OptionType


async def get_expiry_list():
    expiry_list = eval(await redis.get("expiry_list"))
    return [datetime.strptime(expiry, EDELWEISS_DATE_FORMAT).date() for expiry in expiry_list]


@lru_cache
async def get_current_and_next_expiry(todays_date):
    is_today_expiry = False
    current_expiry_date = None
    next_expiry_date = None
    expiry_list = await get_expiry_list()
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
            break

    return current_expiry_date, next_expiry_date, is_today_expiry


def get_strike_and_entry_price(
    option_chain, option_type, strike=None, premium=None, future_price=None
):
    # use bisect to find the strike and its price from option chain
    if strike:
        if premium := option_chain.get(strike):
            return strike, premium

        # even if strike is not present in option chain then the closest strike will be fetched
        if option_type == OptionType.CE:
            for option_strike, option_strike_premium in option_chain.items():
                if float(option_strike_premium) != 0.0 and float(option_strike) <= strike:
                    return strike, option_strike_premium

        prev_strike, prev_strike_premium = 0, 0
        if option_type == OptionType.PE:
            for option_strike, option_strike_premium in option_chain.items():
                if float(option_strike_premium) != 0.0 and float(option_strike) >= strike:
                    return prev_strike, prev_strike_premium

                prev_strike, prev_strike_premium = option_strike, option_strike_premium

    elif premium:
        # get the strike and its price which is just less than the premium
        if option_type == OptionType.CE:
            for strike, strike_premium in option_chain.items():
                if float(strike_premium) != 0.0 and float(strike_premium) <= premium:
                    return strike, strike_premium

        prev_strike, prev_strike_premium = 0, 0
        if option_type == OptionType.PE:
            for strike, strike_premium in option_chain.items():
                if float(strike_premium) != 0.0 and float(strike_premium) >= premium:
                    return prev_strike, prev_strike_premium

                prev_strike, prev_strike_premium = strike, strike_premium

    elif future_price:
        # TODO: to fetch the strike based on volume and open interest, add more data to option chain
        pass

    raise Exception("Either premium or strike or future_price should be provided")
