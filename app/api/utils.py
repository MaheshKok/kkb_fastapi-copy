from datetime import datetime

from app.extensions.redis_cache import redis
from app.schemas.enums import ActionEnum
from app.schemas.enums import OptionTypeEnum
from app.utils.constants import EXPIRY_DATE_FORMAT


def get_option_type(action: ActionEnum):
    if action == ActionEnum.BUY:
        return OptionTypeEnum.CE
    elif action == ActionEnum.SELL:
        return OptionTypeEnum.PE


def get_opposite_option_type(option_type: OptionTypeEnum):
    if option_type == OptionTypeEnum.CE:
        return OptionTypeEnum.PE
    elif option_type == OptionTypeEnum.PE:
        return OptionTypeEnum.CE


async def get_expiry_list():
    expiry_list = eval(await redis.get("expiry_list"))
    return [datetime.strptime(expiry, EXPIRY_DATE_FORMAT).date() for expiry in expiry_list]


async def get_current_and_next_expiry():
    todays_date = datetime.now().date()
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
