import asyncio
import json
import logging
from datetime import datetime
from typing import List

from httpx import AsyncClient
from pydantic import TypeAdapter
from sqlalchemy import select

from app.api.utils import get_current_and_next_expiry_from_redis
from app.core.config import get_config
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.database.models import StrategyModel
from app.database.session_manager.db_session import Database
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.tasks.tasks import task_entry_trade
from app.tasks.tasks import task_exit_trade
from app.tasks.utils import get_future_price
from app.utils.constants import SYMBOL
from app.utils.constants import OptionType


# TODO: test this
async def rollover_to_next_expiry():
    config = get_config()
    Database.init(get_db_url(config))

    # use different strategy to make it faster and efficient
    config = get_config()
    async_redis_client = get_redis_client(config)
    async_httpx_client = AsyncClient()

    future_price_cache = {}
    async with Database() as async_session:
        # get all strategy from database
        strategy_models_query = await async_session.execute(select(StrategyModel))
        strategy_models = strategy_models_query.scalars().all()

        tasks = []
        for strategy_model in strategy_models:
            strategy_schema = StrategySchema.model_validate(strategy_model)

            (
                current_expiry,
                next_expiry,
                todays_expiry,
            ) = await get_current_and_next_expiry_from_redis(async_redis_client, strategy_schema)

            if not todays_expiry:
                continue

            # fetch redis trades
            redis_strategy_data = await async_redis_client.hgetall(str(strategy_schema.id))

            live_trade_option_type_list = [
                OptionType.CE if OptionType.CE in key else OptionType.PE
                for key in redis_strategy_data.keys()
            ]
            if live_trade_option_type_list:
                live_trade_option_type = live_trade_option_type_list[0]

            redis_hash = f"{current_expiry} {live_trade_option_type}"
            if redis_hash not in redis_strategy_data:
                logging.info(
                    f"No trades found for {strategy_schema.id} {strategy_schema.symbol} on {redis_hash}"
                )
                continue

            exiting_trades_json_list = json.loads(redis_strategy_data[redis_hash])
            logging.info(f"Existing total: {len(exiting_trades_json_list)} trades to be closed")
            redis_trade_schema_list = TypeAdapter(List[RedisTradeSchema]).validate_python(
                [json.loads(trade) for trade in exiting_trades_json_list]
            )

            if strategy_schema.symbol in future_price_cache:
                future_entry_price_received = future_price_cache[strategy_schema.symbol]
            else:
                future_entry_price_received = await get_future_price(
                    async_redis_client, strategy_schema
                )
                future_price_cache[strategy_schema.symbol] = future_entry_price_received

            # payload should be like closing live trades so option_type should be opposite to that of redis trades
            payload = {
                "quantity": sum([trade.quantity for trade in redis_trade_schema_list]),
                "future_entry_price_received": future_entry_price_received,
                "strategy_id": strategy_schema.id,
                "option_type": OptionType.CE
                if live_trade_option_type == OptionType.CE
                else OptionType.PE,
                "position": strategy_schema.position,
                "received_at": datetime.now().isoformat(),
                "premium": 400.0 if strategy_schema.symbol == SYMBOL.BANKNIFTY else 200.0,
                "expiry": next_expiry,
            }

            signal_payload_schema = SignalPayloadSchema(**payload)
            exit_task = asyncio.create_task(
                task_exit_trade(
                    signal_payload_schema=signal_payload_schema,
                    async_redis_client=async_redis_client,
                    strategy_schema=strategy_schema,
                    async_httpx_client=async_httpx_client,
                    redis_strategy_key_hash=f"{strategy_schema.id} {redis_hash}",
                    redis_trade_schema_list=redis_trade_schema_list,
                )
            )
            buy_task = asyncio.create_task(
                task_entry_trade(
                    signal_payload_schema=signal_payload_schema,
                    async_redis_client=async_redis_client,
                    strategy_schema=strategy_schema,
                    async_httpx_client=async_httpx_client,
                )
            )
            tasks.append(exit_task)
            tasks.append(buy_task)

        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(rollover_to_next_expiry())
