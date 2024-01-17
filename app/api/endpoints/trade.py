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
from app.api.utils import get_funds_to_use
from app.api.utils import get_lots_to_trade_and_profit_or_loss
from app.api.utils import open_capital_lots
from app.broker.AsyncCapital import AsyncCapitalClient
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import CFDStrategySchema
from app.schemas.strategy import StrategySchema
from app.schemas.trade import BinanceFuturesPayloadSchema
from app.schemas.trade import CFDPayloadSchema
from app.schemas.trade import DBEntryTradeSchema
from app.schemas.trade import FuturesPayloadSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.tasks.tasks import close_trades_in_db_and_remove_from_redis
from app.tasks.tasks import compute_trade_data_needed_for_closing_trade
from app.tasks.tasks import task_entry_trade
from app.tasks.tasks import task_exit_trade
from app.tasks.utils import get_monthly_expiry_date


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

    if futures_payload_schema.side == SignalTypeEnum.BUY.value.upper():
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
        funds_to_use = await get_funds_to_use(client, cfd_strategy_schema)
        lots_to_open, update_profit_or_loss_in_db = get_lots_to_trade_and_profit_or_loss(
            funds_to_use, cfd_strategy_schema, profit_or_loss
        )

        return await open_capital_lots(
            client=client,
            cfd_strategy_schema=cfd_strategy_schema,
            cfd_payload_schema=cfd_payload_schema,
            demo_or_live=demo_or_live,
            profit_or_loss=profit_or_loss,
            lots_to_open=lots_to_open,
            update_profit_or_loss_in_db=update_profit_or_loss_in_db,
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


@options_router.post("/options", status_code=200)
async def post_nfo_indian_options(
    signal_payload_schema: SignalPayloadSchema,
    strategy_schema: StrategySchema = Depends(get_strategy_schema),
    async_redis_client: Redis = Depends(get_async_redis_client),
    async_httpx_client: AsyncClient = Depends(get_async_httpx_client),
):
    start_time = time.perf_counter()
    set_option_type(strategy_schema, signal_payload_schema)

    logging.info(
        f"Received signal payload to buy: [ {signal_payload_schema.option_type} ] for strategy: {strategy_schema.name}"
    )

    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        async_redis_client, strategy_schema
    )
    signal_payload_schema.expiry = current_expiry_date

    trades_key = f"{signal_payload_schema.strategy_id}"
    redis_hash = (
        f"{current_expiry_date} {'PE' if signal_payload_schema.option_type == 'CE' else 'CE'}"
    )

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

            only_futures = (
                True if strategy_schema.instrument_type == InstrumentTypeEnum.FUTIDX else False
            )

            (
                updated_data,
                total_profit,
                total_future_profit,
            ) = await compute_trade_data_needed_for_closing_trade(
                **kwargs,
                redis_trade_schema_list=redis_trade_schema_list,
                only_futures=only_futures,
            )

            lots_to_open, ongoing_profit_or_loss = get_lots_to_trade_and_profit_or_loss(
                funds_to_use=strategy_schema.funds,
                strategy_schema=strategy_schema,
                ongoing_profit_or_loss=total_profit,
            )
            signal_payload_schema.quantity = lots_to_open

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


@options_router.post("/futures", status_code=200)
async def post_nfo_indian_futures(
    futures_payload_schema: FuturesPayloadSchema,
    strategy_schema: CFDStrategySchema = Depends(get_strategy_schema),
    async_redis_client: Redis = Depends(get_async_redis_client),
    async_httpx_client: AsyncClient = Depends(get_async_httpx_client),
):
    start_time = time.perf_counter()
    logging.info(f"Received futures signal payload to buy: [ {strategy_schema.instrument} ]")

    (
        current_month_expiry,
        next_month_expiry,
        is_today_months_expiry,
    ) = await get_monthly_expiry_date(
        async_redis_client=async_redis_client,
        instrument_type=strategy_schema,
        symbol=strategy_schema.instrument,
    )

    trades_key = f"{futures_payload_schema.strategy_id}"
    redis_hash = f"{current_month_expiry} FUT"

    # TODO: in future decide based on strategy new column, strategy_type:
    # if strategy_position is "every" then close all ongoing trades and buy new trade
    # 2. strategy_position is "signal", then on action: EXIT, close same option type trades
    # and buy new trade on BUY action,
    # To be decided in future, the name of actions

    futures_payload_schema.expiry = current_month_expiry

    kwargs = {
        "signal_payload_schema": futures_payload_schema,
        "async_redis_client": async_redis_client,
        "strategy_schema": strategy_schema,
        "async_httpx_client": async_httpx_client,
        "only_futures": True,
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
    else:
        await asyncio.gather(buy_task)
        msg = "successfully bought a new trade"

    process_time = time.perf_counter() - start_time
    logging.info(f" API: [ post_nfo ] request processing time: {process_time} seconds")
    return msg
