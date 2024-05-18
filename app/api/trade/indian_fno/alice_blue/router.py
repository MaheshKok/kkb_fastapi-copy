import datetime
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

from app.api.dependency import get_angelone_client
from app.api.dependency import get_async_httpx_client
from app.api.dependency import get_async_redis_client
from app.api.dependency import get_strategy_pyd_model
from app.api.trade import trading_router
from app.api.trade.indian_fno.alice_blue.tasks import task_entry_trade
from app.api.trade.indian_fno.alice_blue.tasks import task_exit_trade
from app.api.trade.indian_fno.utils import get_current_and_next_expiry_from_redis
from app.api.trade.indian_fno.utils import get_opposite_trade_option_type
from app.api.trade.indian_fno.utils import set_option_type
from app.broker_clients.async_angel_one import AsyncAngelOneClient
from app.database.schemas import TradeDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.enums import InstrumentTypeEnum
from app.pydantic_models.enums import PositionEnum
from app.pydantic_models.enums import SignalTypeEnum
from app.pydantic_models.strategy import StrategyPydanticModel
from app.pydantic_models.trade import DBEntryTradePydanticModel
from app.pydantic_models.trade import RedisTradePydanticModel
from app.pydantic_models.trade import SignalPydanticModel
from app.utils.constants import FUT


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


fno_router = APIRouter(
    prefix=f"{trading_router.prefix}",
    tags=["futures_and_options"],
)


@trading_router.get("/nfo", status_code=200, response_model=List[DBEntryTradePydanticModel])
async def get_open_trades():
    async with Database() as async_session:
        fetch_open_trades_query_ = await async_session.execute(
            select(TradeDBModel).filter(TradeDBModel.exit_at == None)  # noqa
        )
        trade_db_models = fetch_open_trades_query_.scalars().all()
        return trade_db_models


def get_expiry_date_to_trade(
    *,
    current_expiry_date: datetime.date,
    next_expiry_date: datetime.date,
    strategy_pyd_model: StrategyPydanticModel,
    is_today_expiry: bool,
):
    if not is_today_expiry:
        return current_expiry_date

    current_time = datetime.datetime.utcnow()
    if strategy_pyd_model.instrument_type == InstrumentTypeEnum.OPTIDX:
        if strategy_pyd_model.position == PositionEnum.SHORT:
            if current_time.time() > datetime.time(hour=9, minute=45):
                current_expiry_date = next_expiry_date
        else:
            if current_time.time() > datetime.time(hour=8, minute=30):
                current_expiry_date = next_expiry_date
    else:
        if current_time.time() > datetime.time(hour=9, minute=45):
            current_expiry_date = next_expiry_date

    return current_expiry_date


@fno_router.post("/nfo", status_code=200)
async def post_nfo_indian_options(
    signal_pyd_model: SignalPydanticModel,
    strategy_pyd_model: StrategyPydanticModel = Depends(get_strategy_pyd_model),
    async_redis_client: Redis = Depends(get_async_redis_client),
    async_httpx_client: AsyncClient = Depends(get_async_httpx_client),
    async_angelone_client: AsyncAngelOneClient = Depends(get_angelone_client),
):
    crucial_details = f"{strategy_pyd_model.symbol} {strategy_pyd_model.id} {strategy_pyd_model.instrument_type} {signal_pyd_model.action}"
    todays_date = datetime.datetime.utcnow().date()
    start_time = time.perf_counter()
    logging.info(f"[ {crucial_details} ] signal received")

    kwargs = {
        "signal_pyd_model": signal_pyd_model,
        "strategy_pyd_model": strategy_pyd_model,
        "async_redis_client": async_redis_client,
        "async_httpx_client": async_httpx_client,
        "crucial_details": crucial_details,
    }

    (
        current_futures_expiry_date,
        next_futures_expiry_date,
        is_today_futures_expiry,
    ) = await get_current_and_next_expiry_from_redis(
        async_redis_client=async_redis_client,
        instrument_type=InstrumentTypeEnum.FUTIDX,
        symbol=strategy_pyd_model.symbol,
    )

    if (
        strategy_pyd_model.only_on_expiry
        and strategy_pyd_model.instrument_type == InstrumentTypeEnum.FUTIDX
        and current_futures_expiry_date != todays_date
    ):
        return {"message": "Only on expiry"}

    futures_expiry_date = get_expiry_date_to_trade(
        current_expiry_date=current_futures_expiry_date,
        next_expiry_date=next_futures_expiry_date,
        strategy_pyd_model=strategy_pyd_model,
        is_today_expiry=is_today_futures_expiry,
    )

    # fetch opposite position-based trades
    redis_hash = f"{futures_expiry_date} {PositionEnum.SHORT if signal_pyd_model.action == SignalTypeEnum.BUY else PositionEnum.LONG} {FUT}"
    signal_pyd_model.expiry = futures_expiry_date
    kwargs.update(
        {
            "only_futures": True,
            "futures_expiry_date": futures_expiry_date,
        }
    )

    if strategy_pyd_model.instrument_type == InstrumentTypeEnum.OPTIDX:
        set_option_type(strategy_pyd_model, signal_pyd_model)
        (
            current_options_expiry_date,
            next_options_expiry_date,
            is_today_options_expiry,
        ) = await get_current_and_next_expiry_from_redis(
            async_redis_client=async_redis_client,
            instrument_type=InstrumentTypeEnum.OPTIDX,
            symbol=strategy_pyd_model.symbol,
        )

        if (
            strategy_pyd_model.only_on_expiry
            and strategy_pyd_model.instrument_type == InstrumentTypeEnum.OPTIDX
        ):
            if current_options_expiry_date != todays_date:
                return {"message": "Only on expiry"}

            if datetime.datetime.utcnow().time() >= datetime.time(hour=9, minute=45):
                return {"message": "Cannot Trade after 9:45AM GMT on Expiry"}

        options_expiry_date = get_expiry_date_to_trade(
            current_expiry_date=current_options_expiry_date,
            next_expiry_date=next_options_expiry_date,
            strategy_pyd_model=strategy_pyd_model,
            is_today_expiry=is_today_options_expiry,
        )
        # fetch opposite position-based trades
        opposite_trade_option_type = get_opposite_trade_option_type(
            strategy_pyd_model.position, signal_pyd_model.action
        )
        redis_hash = f"{options_expiry_date} {opposite_trade_option_type}"
        signal_pyd_model.expiry = options_expiry_date
        kwargs.update(
            {
                "only_futures": False,
                "options_expiry_date": options_expiry_date,
            }
        )

    trades_key = f"{signal_pyd_model.strategy_id}"
    msg = "successfully"
    if exiting_trades_json := await async_redis_client.hget(trades_key, redis_hash):
        # initiate exit_trade
        exiting_trades_json_list = json.loads(exiting_trades_json)
        logging.info(
            f"[ {crucial_details} ] - Existing total: {len(exiting_trades_json_list)} trades to be closed"
        )
        redis_trade_pyd_model_list = TypeAdapter(List[RedisTradePydanticModel]).validate_python(
            [json.loads(trade) for trade in exiting_trades_json_list]
        )
        ongoing_profit = await task_exit_trade(
            **kwargs,
            redis_hash=redis_hash,
            redis_trade_pyd_model_list=redis_trade_pyd_model_list,
        )
        kwargs["ongoing_profit"] = ongoing_profit
        msg += " closed existing trades and"

    # initiate buy_trade
    await task_entry_trade(
        **kwargs,
        async_angelone_client=async_angelone_client,
    )
    msg += " bought a new trade"

    process_time = round(time.perf_counter() - start_time, 2)
    logging.info(f"[ {crucial_details} ] - request processing time: {process_time} seconds")
    return msg


@fno_router.post("/angelone/nfo", status_code=200)
async def post_nfo_angel_one_trading(
    signal_pyd_model: SignalPydanticModel,
    strategy_pyd_model: StrategyPydanticModel = Depends(get_strategy_pyd_model),
    async_redis_client: Redis = Depends(get_async_redis_client),
    async_httpx_client: AsyncClient = Depends(get_async_httpx_client),
    async_angelone_client: AsyncAngelOneClient = Depends(get_angelone_client),
):
    crucial_details = f"{strategy_pyd_model.symbol} {strategy_pyd_model.id} {strategy_pyd_model.instrument_type} {signal_pyd_model.action}"
    todays_date = datetime.datetime.utcnow().date()
    start_time = time.perf_counter()
    logging.info(f"[ {crucial_details} ] signal received")

    kwargs = {
        "signal_pyd_model": signal_pyd_model,
        "strategy_pyd_model": strategy_pyd_model,
        "async_redis_client": async_redis_client,
        "async_httpx_client": async_httpx_client,
        "crucial_details": crucial_details,
    }

    (
        current_futures_expiry_date,
        next_futures_expiry_date,
        is_today_futures_expiry,
    ) = await get_current_and_next_expiry_from_redis(
        async_redis_client=async_redis_client,
        instrument_type=InstrumentTypeEnum.FUTIDX,
        symbol=strategy_pyd_model.symbol,
    )

    if (
        strategy_pyd_model.only_on_expiry
        and strategy_pyd_model.instrument_type == InstrumentTypeEnum.FUTIDX
        and current_futures_expiry_date != todays_date
    ):
        return {"message": "Only on expiry"}

    futures_expiry_date = get_expiry_date_to_trade(
        current_expiry_date=current_futures_expiry_date,
        next_expiry_date=next_futures_expiry_date,
        strategy_pyd_model=strategy_pyd_model,
        is_today_expiry=is_today_futures_expiry,
    )

    # fetch opposite position-based trades
    redis_hash = f"{futures_expiry_date} {PositionEnum.SHORT if signal_pyd_model.action == SignalTypeEnum.BUY else PositionEnum.LONG} {FUT}"
    signal_pyd_model.expiry = futures_expiry_date
    kwargs.update(
        {
            "only_futures": True,
            "futures_expiry_date": futures_expiry_date,
        }
    )

    if strategy_pyd_model.instrument_type == InstrumentTypeEnum.OPTIDX:
        set_option_type(strategy_pyd_model, signal_pyd_model)
        (
            current_options_expiry_date,
            next_options_expiry_date,
            is_today_options_expiry,
        ) = await get_current_and_next_expiry_from_redis(
            async_redis_client=async_redis_client,
            instrument_type=InstrumentTypeEnum.OPTIDX,
            symbol=strategy_pyd_model.symbol,
        )

        if (
            strategy_pyd_model.only_on_expiry
            and strategy_pyd_model.instrument_type == InstrumentTypeEnum.OPTIDX
        ):
            if current_options_expiry_date != todays_date:
                return {"message": "Only on expiry"}

            if datetime.datetime.utcnow().time() >= datetime.time(hour=9, minute=45):
                return {"message": "Cannot Trade after 9:45AM GMT on Expiry"}

        options_expiry_date = get_expiry_date_to_trade(
            current_expiry_date=current_options_expiry_date,
            next_expiry_date=next_options_expiry_date,
            strategy_pyd_model=strategy_pyd_model,
            is_today_expiry=is_today_options_expiry,
        )
        # fetch opposite position-based trades
        opposite_trade_option_type = get_opposite_trade_option_type(
            strategy_pyd_model.position, signal_pyd_model.action
        )
        redis_hash = f"{options_expiry_date} {opposite_trade_option_type}"
        signal_pyd_model.expiry = options_expiry_date
        kwargs.update(
            {
                "only_futures": False,
                "options_expiry_date": options_expiry_date,
            }
        )

    trades_key = f"{signal_pyd_model.strategy_id}"
    msg = "successfully"
    if exiting_trades_json := await async_redis_client.hget(trades_key, redis_hash):
        # initiate exit_trade
        exiting_trades_json_list = json.loads(exiting_trades_json)
        logging.info(
            f"[ {crucial_details} ] - Existing total: {len(exiting_trades_json_list)} trades to be closed"
        )
        redis_trade_pyd_model_list = TypeAdapter(List[RedisTradePydanticModel]).validate_python(
            [json.loads(trade) for trade in exiting_trades_json_list]
        )
        ongoing_profit = await task_exit_trade(
            **kwargs,
            redis_hash=redis_hash,
            redis_trade_pyd_model_list=redis_trade_pyd_model_list,
        )
        kwargs["ongoing_profit"] = ongoing_profit
        msg += " closed existing trades and"

    # initiate buy_trade
    await task_entry_trade(
        **kwargs,
        async_angelone_client=async_angelone_client,
    )
    msg += " bought a new trade"

    process_time = round(time.perf_counter() - start_time, 2)
    logging.info(f"[ {crucial_details} ] - request processing time: {process_time} seconds")
    return msg
