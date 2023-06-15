import json

from sqlalchemy import select

from app.database.models import TradeModel
from app.utils.constants import OptionType


async def cache_ongoing_trades(app, async_redis):
    """
    fetch all ongoing trades using filter exited_at=None from db using sqlalchemy
    create an empty dict redis_key_trades_dict ={}
    loop through all the ongoing trades
        create a key using strategy_id, expiry and option_type
        store all ongoing trades against the key in redis_key_trades_dict

    now loop through redis_key_trades_dict
        if the key has an empty list then delete the key, value from redis
        if the key is not present in redis then store the ongoing trades in redis using the key
        if the key is present in redis but the length of ongoing trades in redis is not equal to the length of ongoing trades in db
        then also store the ongoing trades in redis using the key

    this will make sure that if theres any discrepancy in db and redis, then redis will be updated

    """

    async with app.state.async_session_maker() as session:
        # TODO: query the database for Trade table and filter by exited_at=None
        # if its possible to get the result in the same manner i.e
        # key should be combination of three columns strategy_id, expiry and option_type
        # then we can avoid the for loop and the redis_key_trades_dict

        result = await session.execute(select(TradeModel).filter_by(exit_at=None))
        db_ongoing_trades = result.scalars().all()
        redis_key_trades_dict = {}
        for ongoing_trade in db_ongoing_trades:
            key = (
                f"{ongoing_trade.strategy_id} {ongoing_trade.expiry} {ongoing_trade.option_type}"
            )

            redis_key_trades_dict[key] = redis_key_trades_dict.get(key, []) + [ongoing_trade]

            # counter_key is used to store the counter trade for the ongoing trade
            # if the ongoing trade is CE then the counter trade is PE and vice versa
            counter_key = f"{ongoing_trade.strategy_id} {ongoing_trade.expiry} {OptionType.CE if ongoing_trade.option_type == OptionType.PE else OptionType.PE}"
            redis_key_trades_dict[counter_key] = []

        # pipeline ensures theres one round trip to redis
        async with async_redis.pipeline() as pipe:
            # store ongoing trades in redis for faster access
            for key, db_trades_in_redis_structure in redis_key_trades_dict.items():
                # this will make sure that if theres any discrepancy in db and redis, then redis will be updated
                if not db_trades_in_redis_structure:
                    await async_redis.delete(key)
                    continue

                redis_trades = json.loads(await async_redis.get(key) or "[]")
                # if ongoing trades are not present in redis or
                # if the length of ongoing trades in redis is not equal to the length of ongoing trades in db
                # then update the ongoing trades in redis
                if not redis_trades:
                    await async_redis.set(key, json.dumps(db_trades_in_redis_structure))
                elif redis_trades and len(redis_trades) != len(db_trades_in_redis_structure):
                    await async_redis.set(key, json.dumps(db_trades_in_redis_structure))
            await pipe.execute()
