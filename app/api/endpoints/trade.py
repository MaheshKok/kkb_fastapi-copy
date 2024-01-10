import asyncio
import json
import logging
import time
import traceback
from http.client import HTTPException  # noqa
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
from app.api.dependency import get_cfd_strategy_schema
from app.api.dependency import get_strategy_schema
from app.api.utils import close_capital_lots
from app.api.utils import get_capital_cfd_existing_profit_or_loss
from app.api.utils import get_current_and_next_expiry
from app.api.utils import open_capital_lots
from app.broker.AsyncCapital import AsyncCapitalClient
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import DirectionEnum
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.strategy import CFDStrategySchema
from app.schemas.strategy import StrategySchema
from app.schemas.trade import BinanceFuturesPayloadSchema
from app.schemas.trade import CFDPayloadSchema
from app.schemas.trade import DBEntryTradeSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
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
    if futures_payload_schema.is_live:
        api_key = "8eV439YeuT1JM5mYF0mX34jKSOakRukolfGayaF9Sj6FMBC4FV1qTHKUqycrpQ4T"
        api_secret = "gFdKzcNXMvDoNfy1YbLNuS0hifnpE5gphs9iTkkyECv6TuYz5pRM4U4vwoNPQy6Q"
        bnc_async_client = BinanceAsyncClient(
            api_key=api_key, api_secret=api_secret, testnet=False
        )
    else:
        api_key = "75d5c54b190c224d6527440534ffe2bfa2afb34c0ccae79beadf560b9d2c5c56"
        api_secret = "db135fa6b2de30c06046891cc1eecfb50fddff0a560043dcd515fd9a57807a37"
        bnc_async_client = BinanceAsyncClient(
            api_key=api_key, api_secret=api_secret, testnet=True
        )

    ltp = round(float(futures_payload_schema.ltp), 2)
    if futures_payload_schema.symbol == "BTCUSDT":
        offset = 5
        ltp = int(ltp)
    elif futures_payload_schema.symbol == "ETHUSDT":
        offset = 0.5
    elif futures_payload_schema.symbol == "LTCUSDT":
        offset = 0.05
    elif futures_payload_schema.symbol == "ETCUSDT":
        offset = 0.03
    else:
        return f"Invalid Symbol: {futures_payload_schema.symbol}"

    if futures_payload_schema.side == DirectionEnum.BUY.value.upper():
        price = round(ltp + offset, 2)
    else:
        price = round(ltp - offset, 2)

    attempt = 1
    while attempt <= 10:
        try:
            existing_position = await bnc_async_client.futures_position_information(
                symbol=futures_payload_schema.symbol
            )

            existing_quantity = 0
            if existing_position:
                existing_quantity = abs(float(existing_position[0]["positionAmt"]))

            quantity_to_place = round(futures_payload_schema.quantity + existing_quantity, 2)
            result = await bnc_async_client.futures_create_order(
                symbol=futures_payload_schema.symbol,
                side=futures_payload_schema.side,
                type=futures_payload_schema.type,
                quantity=quantity_to_place,
                timeinforce="GTC",
                price=price,
            )
            return result
        except Exception as e:
            msg = f"Error occured while placing binance order, Error: {e}"
            logging.error(msg)
            attempt += 1
            await asyncio.sleep(1)


@forex_router.post("/", status_code=200)
async def post_cfd(
    cfd_payload_schema: CFDPayloadSchema,
    cfd_strategy_schema: CFDStrategySchema = Depends(get_cfd_strategy_schema),
):
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"
    logging.info(
        f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : signal [ {cfd_payload_schema.direction} ] received"
    )

    client = AsyncCapitalClient(
        username="maheshkokare100@gmail.com",
        password="SUua9Ydc83G.i!d",
        api_key="qshPG64m0RCWQ3fe",
        demo=cfd_strategy_schema.is_demo,
    )

    profit_or_loss, current_open_lots, direction = await get_capital_cfd_existing_profit_or_loss(
        client, cfd_strategy_schema
    )

    if current_open_lots:
        position_reversed = await close_capital_lots(
            client=client,
            cfd_strategy_schema=cfd_strategy_schema,
            cfd_payload_schema=cfd_payload_schema,
            demo_or_live=demo_or_live,
            lots_to_close=current_open_lots,
            profit_or_loss=profit_or_loss,
        )

        if position_reversed:
            msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : lots [ {current_open_lots} ] are reversed in [ {direction} ] direction,  hence skipping opening new positions"
            logging.info(msg)
            return msg

    if direction != cfd_payload_schema.direction.upper():
        return await open_capital_lots(
            client=client,
            cfd_strategy_schema=cfd_strategy_schema,
            cfd_payload_schema=cfd_payload_schema,
            demo_or_live=demo_or_live,
            profit_or_loss=profit_or_loss,
        )
    else:
        msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : signal [ {cfd_payload_schema.direction} ] is same as current direction, hence skipping opening new positions"
        logging.info(msg)
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
