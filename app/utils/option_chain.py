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
    option_chain = await redis.hgetall(f"{symbol} {expiry} {future_or_option_type}")
    if option_chain:
        if option_type == "CE":
            return dict(sorted(option_chain.items()))
        else:
            return dict(sorted(option_chain.items(), reverse=True))
    raise Exception(f"No option data: [{symbol} {expiry} {future_or_option_type}] found in redis")
