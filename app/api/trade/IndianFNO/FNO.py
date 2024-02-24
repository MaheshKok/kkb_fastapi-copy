import json
import logging
import time
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
from app.api.trade import trading_router
from app.api.trade.Capital.utils import get_lots_to_trade_and_profit_or_loss
from app.api.trade.IndianFNO.tasks import task_entry_trade
from app.api.trade.IndianFNO.tasks import task_exit_trade
from app.api.trade.IndianFNO.utils import get_current_and_next_expiry_from_redis
from app.api.trade.IndianFNO.utils import get_monthly_expiry_date_from_redis
from app.api.trade.IndianFNO.utils import get_opposite_trade_option_type
from app.api.trade.IndianFNO.utils import set_option_type
from app.api.trade.IndianFNO.utils import set_quantity
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import DBEntryTradeSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
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


@fno_router.post("/nfo", status_code=200)
async def post_nfo_indian_options(
    signal_payload_schema: SignalPayloadSchema,
    strategy_schema: StrategySchema = Depends(get_strategy_schema),
    async_redis_client: Redis = Depends(get_async_redis_client),
    async_httpx_client: AsyncClient = Depends(get_async_httpx_client),
):
    crucial_details = f"{ strategy_schema.symbol} {strategy_schema.id} {strategy_schema.instrument_type} {signal_payload_schema.action}"
    start_time = time.perf_counter()
    logging.info(f"[ {crucial_details} ] signal received")

    kwargs = {
        "signal_payload_schema": signal_payload_schema,
        "strategy_schema": strategy_schema,
        "async_redis_client": async_redis_client,
        "async_httpx_client": async_httpx_client,
        "crucial_details": crucial_details,
    }

    # hardcoded instrument_type because i want to explicitly get expiry for futures
    # i cant fetch it from strategy_schema.instrument_type because it can be OPTIDX.
    (
        current_futures_expiry_date,
        next_futures_expiry_date,
        is_today_futures_expiry,
    ) = await get_monthly_expiry_date_from_redis(
        async_redis_client=async_redis_client,
        instrument_type=InstrumentTypeEnum.FUTIDX,
        symbol=strategy_schema.symbol,
    )
    # fetch opposite position based trades
    redis_hash = f"{current_futures_expiry_date} {PositionEnum.SHORT if signal_payload_schema.action == SignalTypeEnum.BUY else PositionEnum.LONG} {FUT}"
    signal_payload_schema.expiry = current_futures_expiry_date
    kwargs.update(
        {
            "only_futures": True,
            "futures_expiry_date": current_futures_expiry_date,
        }
    )

    if strategy_schema.instrument_type == InstrumentTypeEnum.OPTIDX:
        set_option_type(strategy_schema, signal_payload_schema)
        (
            current_options_expiry_date,
            next_options_expiry_date,
            is_today_options_expiry,
        ) = await get_current_and_next_expiry_from_redis(async_redis_client, strategy_schema)
        # fetch opposite position based trades
        opposite_trade_option_type = get_opposite_trade_option_type(
            strategy_schema.position, signal_payload_schema.action
        )
        redis_hash = f"{current_options_expiry_date} {opposite_trade_option_type}"
        signal_payload_schema.expiry = current_options_expiry_date
        kwargs.update(
            {
                "only_futures": False,
                "options_expiry_date": current_options_expiry_date,
            }
        )

    trades_key = f"{signal_payload_schema.strategy_id}"
    lots_to_open = None
    msg = "successfully"
    if exiting_trades_json := await async_redis_client.hget(trades_key, redis_hash):
        # initiate exit_trade
        exiting_trades_json_list = json.loads(exiting_trades_json)
        logging.info(
            f"[ {crucial_details} ] - Existing total: {len(exiting_trades_json_list)} trades to be closed"
        )
        redis_trade_schema_list = TypeAdapter(List[RedisTradeSchema]).validate_python(
            [json.loads(trade) for trade in exiting_trades_json_list]
        )
        lots_to_open = await task_exit_trade(
            **kwargs,
            redis_hash=redis_hash,
            redis_trade_schema_list=redis_trade_schema_list,
        )

        msg += " closed existing trades and"

    if not lots_to_open:
        lots_to_open, ongoing_profit_or_loss = get_lots_to_trade_and_profit_or_loss(
            funds_to_use=strategy_schema.funds,
            strategy_schema=strategy_schema,
            ongoing_profit_or_loss=0.0,
            crucial_details=crucial_details,
        )

    set_quantity(
        strategy_schema=strategy_schema,
        signal_payload_schema=signal_payload_schema,
        lots_to_open=lots_to_open,
    )
    # initiate buy_trade
    await task_entry_trade(
        **kwargs,
    )
    msg += " bought a new trade"

    process_time = round(time.perf_counter() - start_time, 2)
    logging.info(f" [ {crucial_details} ] - request processing time: {process_time} seconds")
    return msg
