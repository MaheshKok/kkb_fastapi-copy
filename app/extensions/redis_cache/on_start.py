import json
import logging

from sqlalchemy import select

from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.trade import RedisTradeSchema


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

    async with Database() as async_session:
        # TODO: query the database for Trade table and filter by exited_at=None
        # if its possible to get the result in the same manner i.e
        # key should be combination of three columns strategy_id, expiry and option_type
        # then we can avoid the for loop and the redis_key_trade_models_dict

        live_trades_query = await async_session.execute(
            select(TradeModel).filter_by(exit_at=None)
        )
        ongoing_trades_model = live_trades_query.scalars().all()
        redis_key_trade_models_dict = {}
        for ongoing_trade_model in ongoing_trades_model:
            redis_hash = f"{ongoing_trade_model.expiry} {ongoing_trade_model.option_type}"
            strategy_id = f"{ongoing_trade_model.strategy_id}"
            if strategy_id not in redis_key_trade_models_dict:
                redis_key_trade_models_dict[strategy_id] = {redis_hash: []}
            if (
                strategy_id in redis_key_trade_models_dict
                and redis_hash not in redis_key_trade_models_dict[strategy_id]
            ):
                redis_key_trade_models_dict[strategy_id][redis_hash] = []

            redis_key_trade_models_dict[strategy_id][redis_hash].append(ongoing_trade_model)

        # pipeline ensures theres one round trip to redis
        async with async_redis_client.pipeline() as pipe:
            # store ongoing trades in redis for faster access
            for (
                strategy_id,
                redis_strategy_hash_trade_models_dict,
            ) in redis_key_trade_models_dict.items():
                for (
                    redis_strategy_hash,
                    trade_models_list,
                ) in redis_strategy_hash_trade_models_dict.items():
                    # if ongoing trades are not present in redis or
                    # if the length of ongoing trades in redis is not equal to the length of ongoing trades in db
                    # then update the ongoing trades in redis

                    # this will make sure that if theres any discrepancy in db and redis, then redis will be updated
                    if not trade_models_list:
                        async_redis_client.hdel(strategy_id, redis_strategy_hash)
                        continue

                    trades_in_redis_json = await async_redis_client.hget(
                        strategy_id, redis_strategy_hash
                    )
                    trades_in_redis = None
                    if trades_in_redis_json:
                        trades_in_redis = json.loads(trades_in_redis_json)
                    if (
                        not trades_in_redis
                        or trades_in_redis
                        and len(trades_in_redis) != len(trade_models_list)
                    ):
                        redis_trades_schema_json_list = [
                            RedisTradeSchema.model_validate(trade_model).model_dump_json()
                            for trade_model in trade_models_list
                        ]
                        result = await async_redis_client.hset(
                            strategy_id,
                            redis_strategy_hash,
                            json.dumps(redis_trades_schema_json_list),
                        )
                        if result:
                            logging.info(
                                f"Ongoing trades cached in redis for {strategy_id} {redis_strategy_hash}"
                            )
                        else:
                            logging.error(
                                f"Ongoing trades not cached in redis for {strategy_id} {redis_strategy_hash}"
                            )

        await pipe.execute()
        logging.info("Ongoing trades cached in redis")
