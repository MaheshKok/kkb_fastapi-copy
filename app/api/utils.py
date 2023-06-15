from datetime import datetime

from app.utils.constants import EDELWEISS_DATE_FORMAT
from app.utils.in_memory_cache import current_and_next_expiry_cache


async def get_expiry_list(async_redis):
    expiry_list = eval(await async_redis.get("expiry_list"))
    return [datetime.strptime(expiry, EDELWEISS_DATE_FORMAT).date() for expiry in expiry_list]


async def get_current_and_next_expiry(async_redis, todays_date):
    if todays_date in current_and_next_expiry_cache:
        return current_and_next_expiry_cache[todays_date]

    is_today_expiry = False
    current_expiry_date = None
    next_expiry_date = None
    expiry_list = await get_expiry_list(async_redis)
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

    current_and_next_expiry_cache[todays_date] = (
        current_expiry_date,
        next_expiry_date,
        is_today_expiry,
    )

    return current_expiry_date, next_expiry_date, is_today_expiry
