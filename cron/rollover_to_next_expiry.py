import asyncio
import json
import logging
from datetime import datetime

# from datetime import datetime
from typing import List

from httpx import AsyncClient
from pydantic import TypeAdapter
from sqlalchemy import select

from app.api.dependency import get_angelone_client
from app.api.trade.IndianFNO.tasks import task_entry_trade
from app.api.trade.IndianFNO.tasks import task_exit_trade
from app.api.trade.IndianFNO.utils import get_current_and_next_expiry_from_redis
from app.api.trade.IndianFNO.utils import get_future_price_from_redis
from app.api.trade.IndianFNO.utils import set_option_type
from app.core.config import get_config
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.database.models import StrategyModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.enums import InstrumentTypeEnum
from app.pydantic_models.enums import PositionEnum
from app.pydantic_models.enums import SignalTypeEnum
from app.pydantic_models.strategy import StrategyPydanticModel
from app.pydantic_models.trade import RedisTradePydanticModel
from app.pydantic_models.trade import SignalPydanticModel
from app.utils.constants import OptionType


def get_action(
    strategy_pydantic_model: StrategyPydanticModel, trade_model: RedisTradePydanticModel
):
    if strategy_pydantic_model.instrument_type == InstrumentTypeEnum.OPTIDX:
        if strategy_pydantic_model.position == PositionEnum.LONG:
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
async def rollover_to_next_expiry(
    instrument_type: InstrumentTypeEnum, position: PositionEnum = None
):
    config = get_config()
    Database.init(get_db_url(config))

    # use different strategy to make it faster and efficient
    async_redis_client = get_redis_client(config)
    async_httpx_client = AsyncClient()
    async_angelone_client = await get_angelone_client(
        config=config, async_redis_client=async_redis_client
    )
    future_price_cache = {}
    async with Database() as async_session:
        # get all strategies from database
        if position:
            strategy_models_query = await async_session.execute(
                select(StrategyModel).filter_by(
                    instrument_type=instrument_type,
                    position=position,
                )
            )
        else:
            strategy_models_query = await async_session.execute(
                select(StrategyModel).filter_by(
                    instrument_type=instrument_type,
                )
            )
        strategy_models = strategy_models_query.scalars().all()

        tasks = []
        for strategy_model in strategy_models:
            strategy_pydantic_model = StrategyPydanticModel.model_validate(strategy_model)

            # TODO: consider caching this expiry in local memory
            (
                futures_current_expiry,
                futures_next_expiry,
                is_today_futures_expiry,
            ) = await get_current_and_next_expiry_from_redis(
                async_redis_client=async_redis_client,
                instrument_type=InstrumentTypeEnum.FUTIDX,
                symbol=strategy_pydantic_model.symbol,
            )

            if strategy_pydantic_model.instrument_type == InstrumentTypeEnum.OPTIDX:
                (
                    options_current_expiry,
                    options_next_expiry,
                    is_today_options_expiry,
                ) = await get_current_and_next_expiry_from_redis(
                    async_redis_client=async_redis_client,
                    instrument_type=InstrumentTypeEnum.OPTIDX,
                    symbol=strategy_pydantic_model.symbol,
                )

                if not is_today_options_expiry:
                    continue
            else:
                if not is_today_futures_expiry:
                    continue

            # fetch redis trades
            redis_strategy_data = await async_redis_client.hgetall(
                str(strategy_pydantic_model.id)
            )
            if strategy_pydantic_model.instrument_type == InstrumentTypeEnum.OPTIDX:
                redis_trades_hash_list = [
                    key
                    for key in redis_strategy_data.keys()
                    if str(options_current_expiry) in key
                ]
            else:
                redis_trades_hash_list = [
                    key
                    for key in redis_strategy_data.keys()
                    if str(futures_current_expiry) in key
                ]

            if redis_trades_hash_list:
                # lets hope at any point of time we don't have both CE and PE open
                redis_hash = redis_trades_hash_list[0]
            else:
                logging.warning(
                    f"No trades found for strategy [ {strategy_pydantic_model.symbol} ] in redis"
                )
                continue

            exiting_trades_json_list = json.loads(redis_strategy_data[redis_hash])
            logging.info(f"Existing total: {len(exiting_trades_json_list)} trades to be closed")
            redis_trade_pydantic_model_list = TypeAdapter(
                List[RedisTradePydanticModel]
            ).validate_python([json.loads(trade) for trade in exiting_trades_json_list])

            if strategy_pydantic_model.symbol in future_price_cache:
                future_entry_price_received = future_price_cache[strategy_pydantic_model.symbol]
            else:
                future_entry_price_received = await get_future_price_from_redis(
                    async_redis_client=async_redis_client,
                    strategy_pydantic_model=strategy_pydantic_model,
                    expiry_date=futures_current_expiry,
                )
                future_price_cache[strategy_pydantic_model.symbol] = future_entry_price_received

            trade_pydantic_model = redis_trade_pydantic_model_list[0]
            signal_payload = {
                "future_entry_price_received": future_entry_price_received,
                "strategy_id": strategy_pydantic_model.id,
                "action": trade_pydantic_model.action,
                "received_at": str(datetime.utcnow().isoformat()),
            }

            signal_pydantic_model = SignalPydanticModel(**signal_payload)
            kwargs = {
                "signal_pydantic_model": signal_pydantic_model,
                "strategy_pydantic_model": strategy_pydantic_model,
                "async_redis_client": async_redis_client,
                "async_httpx_client": async_httpx_client,
                "only_futures": True,
                "futures_expiry_date": futures_current_expiry,
                "crucial_details": f"{strategy_pydantic_model.symbol} {strategy_pydantic_model.id} {strategy_pydantic_model.instrument_type} {trade_pydantic_model.action}",
            }

            if strategy_pydantic_model.instrument_type == InstrumentTypeEnum.OPTIDX:
                kwargs.update(
                    {
                        "only_futures": False,
                        "options_expiry_date": options_current_expiry,
                    }
                )

            ongoing_profit = await task_exit_trade(
                **kwargs,
                redis_hash=redis_hash,
                redis_trade_pydantic_model_list=redis_trade_pydantic_model_list,
            )

            if strategy_pydantic_model.only_on_expiry:
                # do not carry forward if only on expiry
                continue

            if strategy_pydantic_model.instrument_type == InstrumentTypeEnum.OPTIDX:
                # set option_type
                set_option_type(strategy_pydantic_model, signal_pydantic_model)

            if not strategy_pydantic_model.instrument_type == InstrumentTypeEnum.FUTIDX:
                kwargs["options_expiry_date"] = options_next_expiry
                signal_pydantic_model.expiry = options_next_expiry
            else:
                # update expiry in kwargs
                kwargs["futures_expiry_date"] = futures_next_expiry
                signal_pydantic_model.expiry = futures_next_expiry

            kwargs["ongoing_profit"] = ongoing_profit
            buy_task = asyncio.create_task(
                task_entry_trade(
                    **kwargs,
                    async_angelone_client=async_angelone_client,
                )
            )
            tasks.append(buy_task)
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(rollover_to_next_expiry(InstrumentTypeEnum.OPTIDX))
