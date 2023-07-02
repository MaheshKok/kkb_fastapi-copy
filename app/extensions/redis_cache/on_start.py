import json
import logging

from sqlalchemy import select

from app.database.models import TradeModel
from app.database.sqlalchemy_client.client import Database
from app.schemas.trade import RedisTradeSchema
from app.utils.constants import OptionType


async def cache_ongoing_trades(async_redis_client):
    """
    fetch all ongoing trades using filter exited_at=None from db using sqlalchemy
    create an empty dict redis_key_trade_models_dict ={}
    loop through all the ongoing trades
        create a key using strategy_id, expiry and option_type
        store all ongoing trades against the key in redis_key_trade_models_dict

    now loop through redis_key_trade_models_dict
        if the key has an empty list then delete the key, value from redis
        if the key is not present in redis then store the ongoing trades in redis using the key
        if the key is present in redis but the length of ongoing trades in redis is not equal to the length of ongoing trades in db
        then also store the ongoing trades in redis using the key

    this will make sure that if theres any discrepancy in db and redis, then redis will be updated

    """

    async with Database():
        # TODO: query the database for Trade table and filter by exited_at=None
        # if its possible to get the result in the same manner i.e
        # key should be combination of three columns strategy_id, expiry and option_type
        # then we can avoid the for loop and the redis_key_trade_models_dict

        live_trades_query = await Database.session.execute(
            select(TradeModel).filter_by(exit_at=None)
        )
        ongoing_trades_model = live_trades_query.scalars().all()
        redis_key_trade_models_dict = {}
        for ongoing_trade_model in ongoing_trades_model:
            redis_key = f"{ongoing_trade_model.strategy_id} {ongoing_trade_model.expiry} {ongoing_trade_model.option_type}"
            if redis_key not in redis_key_trade_models_dict:
                redis_key_trade_models_dict[redis_key] = []
            redis_key_trade_models_dict[redis_key].append(ongoing_trade_model)
            # counter_key is used to store the counter trade for the ongoing trade
            # if the ongoing trade is CE then the counter trade is PE and vice versa
            counter_key = f"{ongoing_trade_model.strategy_id} {ongoing_trade_model.expiry} {OptionType.CE if ongoing_trade_model.option_type == OptionType.PE else OptionType.PE}"
            redis_key_trade_models_dict[counter_key] = []

        # pipeline ensures theres one round trip to redis
        async with async_redis_client.pipeline() as pipe:
            # store ongoing trades in redis for faster access
            for key, trade_models in redis_key_trade_models_dict.items():
                # this will make sure that if theres any discrepancy in db and redis, then redis will be updated
                if not trade_models:
                    await async_redis_client.delete(key)
                    continue

                redis_trades_schema_json_list = [
                    RedisTradeSchema.from_orm(trade_model).json() for trade_model in trade_models
                ]

                trades_in_redis = await async_redis_client.lrange(key, 0, -1)
                # if ongoing trades are not present in redis or
                # if the length of ongoing trades in redis is not equal to the length of ongoing trades in db
                # then update the ongoing trades in redis
                if not trades_in_redis:
                    await async_redis_client.rpush(key, json.dumps(redis_trades_schema_json_list))
                elif trades_in_redis and len(trades_in_redis) != len(trade_models):
                    await async_redis_client.delete(key)
                    await async_redis_client.rpush(key, *redis_trades_schema_json_list)

            await pipe.execute()
            logging.info("Ongoing trades cached in redis")
