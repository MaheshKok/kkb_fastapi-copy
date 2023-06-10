import bisect
from datetime import datetime
from functools import lru_cache

from app.extensions.redis_cache import redis
from app.schemas.enums import ActionEnum
from app.schemas.enums import OptionTypeEnum
from app.utils.constants import EDELWEISS_DATE_FORMAT


@lru_cache
def get_option_type(action: ActionEnum):
    if action == ActionEnum.BUY:
        return OptionTypeEnum.CE
    elif action == ActionEnum.SELL:
        return OptionTypeEnum.PE


@lru_cache
def get_opposite_option_type(action: ActionEnum):
    if action == ActionEnum.BUY:
        return OptionTypeEnum.PE
    elif action == ActionEnum.SELL:
        return OptionTypeEnum.CE


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


def find_key_value_less_than_or_equal_to(dictionary, value):
    _keys = dictionary.keys()
    index = bisect.bisect_right(_keys, value)

    if index == 0:
        # No key-value pair with key less than the supplied key
        return None, None

    key = _keys[index - 1]
    return key, dictionary[key]


def get_strike_and_entry_price(option_chain, premium=None, strike=None, future_price=None):
    # use bisect to find the strike and its price from option chain
    if strike:
        # even if strike is not present in option chain then the closest strike will be fetched
        return find_key_value_less_than_or_equal_to(option_chain, strike)

    elif premium:
        # get the strike and its price which is just less than the premium
        return find_key_value_less_than_or_equal_to(option_chain, premium)

    else:
        # TODO: to fetch the strike based on volumne and open interest, add more data to option chain
        if not future_price:
            raise Exception("Either premium or strike or future_price should be provided")
        return find_key_value_less_than_or_equal_to(option_chain, future_price)
