from datetime import datetime

from app.extensions.redis_cache import redis


async def get_current_and_next_expiry():
    expiry_list = await redis.get("expiry_list")

    todays_date = datetime.now().date()
    is_today_expiry = False
    current_expiry_str = None
    next_expiry_str = None
    for index, expiry_str in enumerate(expiry_list):
        expiry_date = datetime.strptime(expiry_str, "%d %b %Y").date()
        if todays_date > expiry_date:
            continue
        elif expiry_date == todays_date:
            next_expiry_str = expiry_list[index + 1]
            current_expiry_str = expiry_str
            is_today_expiry = True
            break
        elif todays_date < expiry_date:
            current_expiry_str = expiry_str
            break

    return current_expiry_str, next_expiry_str, is_today_expiry
