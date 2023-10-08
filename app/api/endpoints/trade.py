import asyncio
import json
import logging
import time
import traceback
from typing import List

from aioredis import Redis
from binance.client import AsyncClient as BinanceAsyncClient
from fastapi import APIRouter
from fastapi import Depends
from httpx import AsyncClient
from pydantic import TypeAdapter
from sqlalchemy import select

from app.api.dependency import get_async_httpx_client
from app.api.dependency import get_async_redis_client
from app.api.dependency import get_strategy_schema
from app.api.utils import get_current_and_next_expiry
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import DirectionEnum
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import BinanceFuturesPayloadSchema
from app.schemas.trade import CFDPayloadSchema
from app.schemas.trade import DBEntryTradeSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.services.broker.Capital import CapitalClient
from app.tasks.tasks import task_entry_trade
from app.tasks.tasks import task_exit_trade


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

trading_router = APIRouter(
    prefix="/api/trading",
    tags=["trading"],
)

options_router = APIRouter(
    prefix=f"{trading_router.prefix}/nfo",
    tags=["options"],
)

futures_router = APIRouter(
    prefix=f"{trading_router.prefix}/nfo",
    tags=["futures"],
)

forex_router = APIRouter(
    prefix=f"{trading_router.prefix}/cfd",
    tags=["forex"],
)


binance_router = APIRouter(
    prefix=f"{trading_router.prefix}/binance",
    tags=["binance"],
)


@binance_router.post("/futures", status_code=200)
async def post_binance_futures(futures_payload_schema: BinanceFuturesPayloadSchema):
    api_key = "75d5c54b190c224d6527440534ffe2bfa2afb34c0ccae79beadf560b9d2c5c56"
    api_secret = "db135fa6b2de30c06046891cc1eecfb50fddff0a560043dcd515fd9a57807a37"
    bnce_async_client = BinanceAsyncClient(api_key=api_key, api_secret=api_secret, testnet=True)
    ltp = int(float(futures_payload_schema.ltp))
    if futures_payload_schema.side == DirectionEnum.BUY.value.upper():
        price = ltp + 10
    else:
        price = ltp - 10

    open_orders = await bnce_async_client.futures_get_open_orders()
    if open_orders:
        # TODO: handle it later
        pass

    try:
        result = await bnce_async_client.futures_create_order(
            symbol=futures_payload_schema.symbol,
            side=futures_payload_schema.side,
            type=futures_payload_schema.type,
            # TODO: make it 1 later
            quantity=2,
            timeinforce="GTC",
            price=price,
        )
        return result
    except Exception as e:
        msg = f"Error occured while placing binance order, Error: {e}"
        logging.error(msg)
        return msg


@forex_router.post("/", status_code=200)
async def post_cfd(cfd_payload_schema: CFDPayloadSchema):
    client = CapitalClient(
        username="maheshkokare100@gmail.com",
        password="SUua9Ydc83G.i!d",
        api_key="qshPG64m0RCWQ3fe",
        demo=True,
    )
    # size would be twice of payload,
    # reason: we have to close the existing position first and enter a new one
    lot_to_trade = 0
    if positions := client.all_positions():
        for position in positions["positions"]:
            if position["market"]["epic"] == cfd_payload_schema.instrument:
                existing_direction = position["position"]["direction"]
                if existing_direction != cfd_payload_schema.direction.upper():
                    # to close exisitng position add those many positions to new trade
                    lot_to_trade = int(position["position"]["size"])

    attempt = 1
    while attempt < 5:
        # it doesnt give exact size of open position, i have to have a local position in db
        response = client.create_position(
            epic=cfd_payload_schema.instrument,
            direction=cfd_payload_schema.direction,
            size=cfd_payload_schema.size + lot_to_trade,
        )
        msg = f"deal status: {response['dealStatus']}, reason: {response['reason']}, status: {response['status']}"
        logging.info(msg)
        if response["dealStatus"] == "REJECTED":
            attempt += 1
            continue
        return msg


@trading_router.get("/", status_code=200, response_model=List[DBEntryTradeSchema])
async def get_open_trades():
    async with Database() as async_session:
        fetch_open_trades_query_ = await async_session.execute(
            select(TradeModel).filter(TradeModel.exit_at == None)  # noqa
        )
        trade_models = fetch_open_trades_query_.scalars().all()
        return trade_models


@options_router.post("/options", status_code=200)
async def post_nfo(
    signal_payload_schema: SignalPayloadSchema,
    strategy_schema: StrategySchema = Depends(get_strategy_schema),
    async_redis_client: Redis = Depends(get_async_redis_client),
    async_httpx_client: AsyncClient = Depends(get_async_httpx_client),
):
    start_time = time.perf_counter()
    logging.info(
        f"Received signal payload to buy: [ {signal_payload_schema.option_type} ] for strategy: {strategy_schema.name}"
    )

    if signal_payload_schema.position == PositionEnum.SHORT:
        # swap option_type i.e for buy signal we will short PE and for sell signal we will short CE
        if signal_payload_schema.option_type == OptionTypeEnum.PE:
            signal_payload_schema.option_type = OptionTypeEnum.CE
        else:
            signal_payload_schema.option_type = OptionTypeEnum.PE

    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        async_redis_client, strategy_schema
    )

    trades_key = f"{signal_payload_schema.strategy_id}"
    redis_hash = (
        f"{current_expiry_date} {'PE' if signal_payload_schema.option_type == 'CE' else 'CE'}"
    )

    # TODO: in future decide based on strategy new column, strategy_type:
    # if strategy_position is "every" then close all ongoing trades and buy new trade
    # 2. strategy_position is "signal", then on action: EXIT, close same option type trades
    # and buy new trade on BUY action,
    # To be decided in future, the name of actions

    signal_payload_schema.expiry = current_expiry_date

    kwargs = {
        "signal_payload_schema": signal_payload_schema,
        "async_redis_client": async_redis_client,
        "strategy_schema": strategy_schema,
        "async_httpx_client": async_httpx_client,
    }
    exit_task = None
    try:
        if exiting_trades_json := await async_redis_client.hget(trades_key, redis_hash):
            # initiate exit_trade
            exiting_trades_json_list = json.loads(exiting_trades_json)
            logging.info(f"Existing total: {len(exiting_trades_json_list)} trades to be closed")
            redis_trade_schema_list = TypeAdapter(List[RedisTradeSchema]).validate_python(
                [json.loads(trade) for trade in exiting_trades_json_list]
            )

            exit_task = asyncio.create_task(
                task_exit_trade(
                    **kwargs,
                    redis_strategy_key_hash=f"{trades_key} {redis_hash}",
                    redis_trade_schema_list=redis_trade_schema_list,
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
        process_time = time.perf_counter() - start_time
    else:
        await asyncio.gather(buy_task)
        msg = "successfully bought a new trade"
        process_time = time.perf_counter() - start_time

    logging.info(f" API: [ post_nfo ] request processing time: {process_time} seconds")
    return msg
