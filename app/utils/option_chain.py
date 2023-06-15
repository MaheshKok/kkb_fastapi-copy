from datetime import datetime

from app.api.utils import get_expiry_list


async def get_option_chain(
    async_redis,
    symbol,
    expiry,
    option_type=None,
    is_future=False,
):
    if is_future and option_type:
        raise ValueError("Futures dont have option_type")

    if is_future:
        current_month_number = datetime.now().date().month
        expiry_list = await get_expiry_list(async_redis)
        for _, expiry_date in enumerate(expiry_list):
            if expiry_date.month > current_month_number:
                break
            expiry = expiry_date

    future_or_option_type = "FUT" if is_future else option_type
    option_chain = await async_redis.hgetall(f"{symbol} {expiry} {future_or_option_type}")
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
    raise Exception(f"No option data: [{symbol} {expiry} {future_or_option_type}] found in redis")
