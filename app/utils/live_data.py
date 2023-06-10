from app.extensions.redis_cache import redis


async def get_option_chain(
    symbol,
    expiry,
    option_type=None,
    is_future=False,
):
    if is_future and expiry:
        raise ValueError("Futures dont have option_type")

    future_or_option_type = "FUT" if is_future else option_type
    option_chain = eval(await redis.hgetall(f"{symbol} {expiry} {future_or_option_type}"))
    return dict(sorted(option_chain.items()))
