import json
import logging

from sqlalchemy import select

from app.database.schemas import StrategyDBModel
from app.database.schemas import TradeDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.enums import PositionEnum
from app.pydantic_models.strategy import StrategyPydModel
from app.pydantic_models.trade import RedisTradePydModel
from app.utils.constants import FUT


async def cache_ongoing_trades(async_redis_client):
    """
    fetch all ongoing trades using filter exited_at=None from db using sqlalchemy
    create an empty dict redis_key_trade_db_models_dict ={}
    loop through all the ongoing trades
        create a key using strategy_id, expiry, and option_type
        store all ongoing trades against the key in redis_key_trade_db_models_dict

    now loop through redis_key_trade_db_models_dict
        if the key has an empty list then delete the key, value from redis
        if the key is not present in redis then store the ongoing trades in redis using the key
        if the key is present in redis, but the length of ongoing trades in redis is not equal to the length of ongoing trades in db
        then also store the ongoing trades in redis using the key

    this will make sure that if there's any discrepancy in db and redis, then redis will be updated

    """

    async with Database() as async_session:
        # TODO: query the database for Trade table and filter by exited_at=None
        # if its possible to get the result in the same manner i.e
        # key should be combination of three columns strategy_id, expiry and option_type
        # then we can avoid the for loop and the redis_key_trade_db_models_dict

        strategy_query = await async_session.execute(select(StrategyDBModel))
        strategy_db_models = strategy_query.scalars().all()
        async with async_redis_client.pipeline() as pipe:
            for strategy_db_model in strategy_db_models:
                pipe.hset(
                    str(strategy_db_model.id),
                    "strategy",
                    StrategyPydModel.model_validate(strategy_db_model).model_dump_json(),
                )
            await pipe.execute()

        logging.info(f"Cached strategy: {len(strategy_db_models)}")
        live_trades_query = await async_session.execute(
            select(TradeDBModel).filter_by(exit_at=None)
        )
        ongoing_trades_model = live_trades_query.scalars().all()
        redis_key_trade_db_models_dict = {
            str(strategy_db_model.id): {} for strategy_db_model in strategy_db_models
        }

        for ongoing_trade_db_model in ongoing_trades_model:
            if ongoing_trade_db_model.option_type:
                redis_hash = (
                    f"{ongoing_trade_db_model.expiry} {ongoing_trade_db_model.option_type}"
                )
            else:
                redis_hash = f"{ongoing_trade_db_model.expiry} {PositionEnum.LONG if ongoing_trade_db_model.quantity > 0 else PositionEnum.SHORT} {FUT}"
            strategy_id = f"{ongoing_trade_db_model.strategy_id}"
            if strategy_id not in redis_key_trade_db_models_dict:
                redis_key_trade_db_models_dict[strategy_id] = {redis_hash: []}
            if (
                strategy_id in redis_key_trade_db_models_dict
                and redis_hash not in redis_key_trade_db_models_dict[strategy_id]
            ):
                redis_key_trade_db_models_dict[strategy_id][redis_hash] = []

            redis_key_trade_db_models_dict[strategy_id][redis_hash].append(ongoing_trade_db_model)

        # pipeline ensures theres one round trip to redis
        async with async_redis_client.pipeline() as pipe:
            # store ongoing trades in redis for faster access
            for (
                strategy_id,
                redis_strategy_hash_trade_db_models_dict,
            ) in redis_key_trade_db_models_dict.items():
                if not redis_strategy_hash_trade_db_models_dict:
                    keys = await async_redis_client.hkeys(strategy_id)
                    for key in keys:
                        if key != "strategy":
                            # this will make sure that if theres any discrepancy in db and redis, then redis will be updated
                            await async_redis_client.hdel(strategy_id, key)

                for (
                    redis_strategy_hash,
                    trade_db_models_list,
                ) in redis_strategy_hash_trade_db_models_dict.items():
                    # if ongoing trades are not present in redis or
                    # if the length of ongoing trades in redis is not equal to the length of ongoing trades in db
                    # then update the ongoing trades in redis

                    # this will make sure that if theres any discrepancy in db and redis, then redis will be updated
                    if not trade_db_models_list:
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
                        and len(trades_in_redis) != len(trade_db_models_list)
                    ):
                        redis_trades_pyd_model_json_list = [
                            RedisTradePydModel.model_validate(trade_db_model).model_dump_json(
                                exclude_none=True
                            )
                            for trade_db_model in trade_db_models_list
                        ]
                        result = await async_redis_client.hset(
                            strategy_id,
                            redis_strategy_hash,
                            json.dumps(redis_trades_pyd_model_json_list),
                        )
                        if result:
                            logging.info(
                                f"Ongoing trades cached in redis for strategy: [ {strategy_id} ], hash: [ {redis_strategy_hash} ]"
                            )
                        else:
                            logging.error(
                                f"Ongoing trades not cached in redis for strategy: [ {strategy_id} ], hash: [ {redis_strategy_hash} ]"
                            )

            await pipe.execute()
        logging.info("Ongoing trades cached in redis")
