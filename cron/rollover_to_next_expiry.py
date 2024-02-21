import asyncio
import json
import logging
from datetime import datetime

# from datetime import datetime
from typing import List

from httpx import AsyncClient
from pydantic import TypeAdapter
from sqlalchemy import select

from app.api.endpoints.trade.indian_futures_and_options import set_option_type
from app.api.utils import get_current_and_next_expiry_from_redis
from app.core.config import get_config
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.database.models import StrategyModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.tasks.tasks import task_entry_trade
from app.tasks.tasks import task_exit_trade
from app.tasks.utils import get_future_price_from_redis
from app.tasks.utils import get_monthly_expiry_date_from_redis
from app.utils.constants import OptionType


def get_action(strategy_schema: StrategySchema, trade_model: RedisTradeSchema):
    if strategy_schema.instrument_type == InstrumentTypeEnum.OPTIDX:
        if strategy_schema.position == PositionEnum.LONG:
            if trade_model.option_type == OptionType.CE:
                return SignalTypeEnum.BUY
            else:
                return SignalTypeEnum.SELL
        else:
            if trade_model.option_type == OptionType.CE:
                return SignalTypeEnum.SELL
            else:
                return SignalTypeEnum.BUY
    else:
        if trade_model.quantity > 0:
            return SignalTypeEnum.BUY
        else:
            return SignalTypeEnum.SELL


# TODO: Test this function
async def rollover_to_next_expiry():
    config = get_config()
    Database.init(get_db_url(config))

    # use different strategy to make it faster and efficient
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

            # TODO: consider caching this expiry in local memory
            (
                futures_current_expiry,
                futures_next_expiry,
                is_today_futures_expiry,
            ) = await get_monthly_expiry_date_from_redis(
                async_redis_client=async_redis_client,
                instrument_type=InstrumentTypeEnum.FUTIDX,
                symbol=strategy_schema.symbol,
            )

            if strategy_schema.instrument_type == InstrumentTypeEnum.OPTIDX:
                (
                    options_current_expiry,
                    options_next_expiry,
                    is_today_options_expiry,
                ) = await get_current_and_next_expiry_from_redis(
                    async_redis_client, strategy_schema
                )

                if not is_today_options_expiry:
                    continue
            else:
                if not is_today_futures_expiry:
                    continue

            # fetch redis trades
            redis_strategy_data = await async_redis_client.hgetall(str(strategy_schema.id))
            redis_trades_hash_list = [
                key for key in redis_strategy_data.keys() if "strategy" not in key
            ]
            if redis_trades_hash_list:
                redis_hash = redis_trades_hash_list[0]
            else:
                logging.warning(
                    f"No trades found for strategy [ {strategy_schema.symbol} ] in redis"
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
                future_entry_price_received = await get_future_price_from_redis(
                    async_redis_client=async_redis_client,
                    strategy_schema=strategy_schema,
                    expiry_date=futures_current_expiry,
                )
                future_price_cache[strategy_schema.symbol] = future_entry_price_received

            trade_schema = redis_trade_schema_list[0]
            signal_payload = {
                "future_entry_price_received": future_entry_price_received,
                "strategy_id": strategy_schema.id,
                "action": trade_schema.action,
                "received_at": str(datetime.utcnow().isoformat()),
            }

            signal_payload_schema = SignalPayloadSchema(**signal_payload)
            kwargs = {
                "signal_payload_schema": signal_payload_schema,
                "strategy_schema": strategy_schema,
                "async_redis_client": async_redis_client,
                "async_httpx_client": async_httpx_client,
                "only_futures": True,
                "futures_expiry_date": futures_current_expiry,
                "crucial_details": f"{strategy_schema.symbol} {strategy_schema.id} {strategy_schema.instrument_type} {trade_schema.action}",
            }

            if strategy_schema.instrument_type == InstrumentTypeEnum.OPTIDX:
                kwargs.update(
                    {
                        "only_futures": False,
                        "options_expiry_date": options_current_expiry,
                    }
                )

            sell_task = asyncio.create_task(
                task_exit_trade(
                    **kwargs,
                    redis_hash=redis_hash,
                    redis_trade_schema_list=redis_trade_schema_list,
                )
            )
            tasks.append(sell_task)

            # set option_type
            set_option_type(strategy_schema, signal_payload_schema)

            if not strategy_schema.instrument_type == InstrumentTypeEnum.FUTIDX:
                kwargs["options_expiry_date"] = options_next_expiry
                signal_payload_schema.expiry = options_next_expiry
            else:
                # update expiry in kwargs
                kwargs["futures_expiry_date"] = futures_next_expiry
                signal_payload_schema.expiry = futures_next_expiry

            signal_payload_schema.quantity = int(
                len(exiting_trades_json_list) * trade_schema.quantity
            )
            buy_task = asyncio.create_task(
                task_entry_trade(
                    **kwargs,
                )
            )
            tasks.append(buy_task)
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(rollover_to_next_expiry())
