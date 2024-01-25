import asyncio
import json
import logging
import time
import traceback
from http.client import HTTPException  # noqa
from typing import List

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends
from httpx import AsyncClient
from pydantic import TypeAdapter
from sqlalchemy import select

from app.api.dependency import get_async_httpx_client
from app.api.dependency import get_async_redis_client
from app.api.dependency import get_strategy_schema
from app.api.endpoints.trade import trading_router
from app.api.utils import get_current_and_next_expiry_from_redis
from app.api.utils import get_lots_to_trade_and_profit_or_loss
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import DBEntryTradeSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.tasks.tasks import close_trades_in_db_and_remove_from_redis
from app.tasks.tasks import compute_trade_data_needed_for_closing_trade
from app.tasks.tasks import task_entry_trade
from app.tasks.utils import get_monthly_expiry_date_from_redis
from app.utils.constants import FUT


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


fno_router = APIRouter(
    prefix=f"{trading_router.prefix}",
    tags=["futures_and_options"],
)


@trading_router.get("/nfo", status_code=200, response_model=List[DBEntryTradeSchema])
async def get_open_trades():
    async with Database() as async_session:
        fetch_open_trades_query_ = await async_session.execute(
            select(TradeModel).filter(TradeModel.exit_at == None)  # noqa
        )
        trade_models = fetch_open_trades_query_.scalars().all()
        return trade_models


def set_option_type(strategy_schema: StrategySchema, payload: SignalPayloadSchema) -> None:
    # set OptionTypeEnum base strategy's position column and signal's action.
    strategy_position_trade = {
        PositionEnum.LONG: {
            SignalTypeEnum.BUY: OptionTypeEnum.CE,
            SignalTypeEnum.SELL: OptionTypeEnum.PE,
        },
        PositionEnum.SHORT: {
            SignalTypeEnum.BUY: OptionTypeEnum.PE,
            SignalTypeEnum.SELL: OptionTypeEnum.CE,
        },
    }

    opposite_trade = {OptionTypeEnum.CE: OptionTypeEnum.PE, OptionTypeEnum.PE: OptionTypeEnum.CE}

    position_based_trade = strategy_position_trade.get(strategy_schema.position)
    payload.option_type = position_based_trade.get(payload.action) or opposite_trade.get(
        payload.option_type
    )


def set_quantity(
    *,
    signal_payload_schema: SignalPayloadSchema,
    quantity: float,
    strategy_schema: StrategySchema,
) -> None:
    if strategy_schema.instrument_type == InstrumentTypeEnum.OPTIDX:
        if strategy_schema.position == PositionEnum.LONG:
            signal_payload_schema.quantity = quantity
        else:
            signal_payload_schema.quantity = -quantity
    else:
        if signal_payload_schema.action == SignalTypeEnum.BUY:
            signal_payload_schema.quantity = quantity
        else:
            signal_payload_schema.quantity = -quantity


@fno_router.post("/nfo", status_code=200)
async def post_nfo_indian_options(
    signal_payload_schema: SignalPayloadSchema,
    strategy_schema: StrategySchema = Depends(get_strategy_schema),
    async_redis_client: Redis = Depends(get_async_redis_client),
    async_httpx_client: AsyncClient = Depends(get_async_httpx_client),
):
    logging.info(
        f"Received signal payload to buy: [ {signal_payload_schema.option_type} ] for strategy: {strategy_schema.name}"
    )

    start_time = time.perf_counter()
    if strategy_schema.instrument_type == InstrumentTypeEnum.OPTIDX:
        set_option_type(strategy_schema, signal_payload_schema)
        (
            current_expiry_date,
            next_expiry_date,
            is_today_expiry,
        ) = await get_current_and_next_expiry_from_redis(async_redis_client, strategy_schema)
        redis_hash = (
            f"{current_expiry_date} {'PE' if signal_payload_schema.option_type == 'CE' else 'CE'}"
        )
        only_futures = False
    else:
        (
            current_expiry_date,
            next_expiry_date,
            is_today_expiry,
        ) = await get_monthly_expiry_date_from_redis(
            async_redis_client=async_redis_client,
            instrument_type=strategy_schema.instrument_type,
            symbol=strategy_schema.symbol,
        )
        redis_hash = f"{current_expiry_date} {PositionEnum.LONG if signal_payload_schema.action == SignalTypeEnum.BUY else PositionEnum.SHORT} {FUT}"
        only_futures = True

    signal_payload_schema.expiry = current_expiry_date
    trades_key = f"{signal_payload_schema.strategy_id}"

    # TODO: in future decide based on strategy new column, strategy_type:
    # if strategy_position is "every" then close all ongoing trades and buy new trade
    # 2. strategy_position is "signal", then on action: EXIT, close same option type trades
    # and buy new trade on BUY action,
    # To be decided in future, the name of actions

    kwargs = {
        "signal_payload_schema": signal_payload_schema,
        "async_redis_client": async_redis_client,
        "strategy_schema": strategy_schema,
        "async_httpx_client": async_httpx_client,
        "only_futures": only_futures,
    }

    lots_to_open, ongoing_profit_or_loss = get_lots_to_trade_and_profit_or_loss(
        funds_to_use=strategy_schema.funds,
        strategy_schema=strategy_schema,
        ongoing_profit_or_loss=0.0,
    )
    signal_payload_schema.quantity = lots_to_open

    exit_task = None
    try:
        if exiting_trades_json := await async_redis_client.hget(trades_key, redis_hash):
            # initiate exit_trade
            exiting_trades_json_list = json.loads(exiting_trades_json)
            logging.info(f"Existing total: {len(exiting_trades_json_list)} trades to be closed")
            redis_trade_schema_list = TypeAdapter(List[RedisTradeSchema]).validate_python(
                [json.loads(trade) for trade in exiting_trades_json_list]
            )

            (
                updated_data,
                total_profit,
                total_future_profit,
            ) = await compute_trade_data_needed_for_closing_trade(
                **kwargs,
                redis_trade_schema_list=redis_trade_schema_list,
            )

            lots_to_open, ongoing_profit_or_loss = get_lots_to_trade_and_profit_or_loss(
                funds_to_use=strategy_schema.funds,
                strategy_schema=strategy_schema,
                ongoing_profit_or_loss=total_profit,
            )

            set_quantity(
                signal_payload_schema=signal_payload_schema,
                quantity=lots_to_open,
                strategy_schema=strategy_schema,
            )

            # update database with the updated data
            exit_task = asyncio.create_task(
                close_trades_in_db_and_remove_from_redis(
                    updated_data=updated_data,
                    strategy_schema=strategy_schema,
                    total_profit=ongoing_profit_or_loss,
                    total_future_profit=total_future_profit,
                    total_redis_trades=len(redis_trade_schema_list),
                    async_redis_client=async_redis_client,
                    redis_strategy_key_hash=f"{trades_key} {redis_hash}",
                )
            )
    except Exception as e:
        logging.error(f"Exception while exiting trade: {e}")
        traceback.print_exc()

    # initiate buy_trade
    buy_task = asyncio.create_task(
        task_entry_trade(
            **kwargs,
        )
    )
    if exit_task:
        await asyncio.gather(exit_task, buy_task)
        msg = "successfully closed existing trades and bought a new trade"
    else:
        await asyncio.gather(buy_task)
        msg = "successfully bought a new trade"

    process_time = time.perf_counter() - start_time
    logging.info(f" API: [ post_nfo ] request processing time: {process_time} seconds")
    return msg
