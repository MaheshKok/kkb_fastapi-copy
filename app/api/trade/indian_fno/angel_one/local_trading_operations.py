import datetime
import json
import logging
from typing import Any
from typing import List

from aioredis import Redis
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.trade.indian_fno.angel_one.broker_trading_operations import get_expiry_date_to_trade
from app.api.trade.indian_fno.angel_one.dependency import get_async_angelone_client
from app.api.trade.indian_fno.angel_one.tasks import task_open_angelone_trade_position
from app.api.trade.indian_fno.utils import calculate_profits
from app.api.trade.indian_fno.utils import close_trades_in_db_and_remove_from_redis
from app.api.trade.indian_fno.utils import get_crucial_details
from app.api.trade.indian_fno.utils import get_current_and_next_expiry_from_redis
from app.api.trade.indian_fno.utils import get_future_price_from_redis
from app.api.trade.indian_fno.utils import get_futures_profit
from app.api.trade.indian_fno.utils import get_opposite_trade_option_type
from app.api.trade.indian_fno.utils import is_options_strategy
from app.api.trade.indian_fno.utils import is_short_strategy
from app.api.trade.indian_fno.utils import push_trade_to_redis
from app.api.trade.indian_fno.utils import set_option_type
from app.database.schemas import TradeDBModel
from app.pydantic_models.angel_one import InitialOrderPydModel
from app.pydantic_models.angel_one import UpdatedOrderPydModel
from app.pydantic_models.enums import InstrumentTypeEnum
from app.pydantic_models.enums import OptionTypeEnum
from app.pydantic_models.enums import PositionEnum
from app.pydantic_models.enums import SignalTypeEnum
from app.pydantic_models.strategy import StrategyPydModel
from app.pydantic_models.trade import FuturesEntryTradePydModel
from app.pydantic_models.trade import OptionsEntryTradePydModel
from app.pydantic_models.trade import RedisTradePydModel
from app.pydantic_models.trade import SignalPydModel
from app.utils.constants import FUT


def get_action(
    strategy_pyd_model: StrategyPydModel, initial_order_pyd_model: InitialOrderPydModel
):
    if is_options_strategy(strategy_pyd_model=strategy_pyd_model):
        if is_short_strategy(strategy_pyd_model=strategy_pyd_model):
            return (
                SignalTypeEnum.BUY
                if initial_order_pyd_model.option_type == OptionTypeEnum.CE
                else SignalTypeEnum.SELL
            )
        return (
            SignalTypeEnum.SELL
            if initial_order_pyd_model.option_type == OptionTypeEnum.CE
            else SignalTypeEnum.BUY
        )
    else:
        return initial_order_pyd_model.action


async def handle_futures_entry_order(
    *,
    async_session: AsyncSession,
    async_redis_client: Redis,
    initial_order_pyd_model: InitialOrderPydModel,
    updated_order_pyd_model: UpdatedOrderPydModel,
    strategy_pyd_model: StrategyPydModel,
    crucial_details: str,
):
    trade_pyd_model = FuturesEntryTradePydModel(
        entry_price=updated_order_pyd_model.averageprice,
        future_entry_price=initial_order_pyd_model.future_entry_price_received,
        quantity=(
            updated_order_pyd_model.quantity
            if initial_order_pyd_model.action == SignalTypeEnum.BUY
            else -updated_order_pyd_model.quantity
        ),
        entry_at=initial_order_pyd_model.entry_at,
        instrument=updated_order_pyd_model.tradingsymbol,
        entry_received_at=initial_order_pyd_model.entry_received_at,
        received_at=initial_order_pyd_model.entry_received_at,
        expiry=initial_order_pyd_model.expiry,
        action=initial_order_pyd_model.action,
        strategy_id=strategy_pyd_model.id,
        future_entry_price_received=initial_order_pyd_model.future_entry_price_received,
    )

    trade_db_model = TradeDBModel(
        **trade_pyd_model.model_dump(
            exclude={
                "premium",
                "broker_id",
                "symbol",
                "received_at",
                "future_entry_price",
            },
            exclude_none=True,
        )
    )
    async_session.add(trade_db_model)
    await async_session.flush([trade_db_model])
    msg = f"[ {crucial_details} ] - new trade: [ {trade_db_model.id} ] added to DB"
    logging.info(msg)
    await push_trade_to_redis(
        async_redis_client=async_redis_client,
        trade_db_model=trade_db_model,
        signal_type=initial_order_pyd_model.action,
        crucial_details=crucial_details,
    )
    return trade_db_model.id


async def handle_futures_exit_order(
    *,
    async_redis_client: Redis,
    async_httpx_client: AsyncClient,
    initial_order_pyd_model: InitialOrderPydModel,
    updated_order_pyd_model: UpdatedOrderPydModel,
    strategy_pyd_model: StrategyPydModel,
):
    action = get_action(strategy_pyd_model, initial_order_pyd_model)
    signal_pyd_model = SignalPydModel(
        strategy_id=strategy_pyd_model.id,
        future_entry_price_received=initial_order_pyd_model.future_entry_price_received,
        received_at=datetime.datetime.utcnow(),
        action=action,
    )

    crucial_details = get_crucial_details(
        signal_pyd_model=signal_pyd_model, strategy_pyd_model=strategy_pyd_model
    )
    kwargs, redis_hash = await get_angel_one_pre_trade_kwargs(
        signal_pyd_model=signal_pyd_model,
        strategy_pyd_model=strategy_pyd_model,
        async_redis_client=async_redis_client,
    )
    kwargs["crucial_details"] = crucial_details

    future_exit_price = await get_future_price_from_redis(
        async_redis_client=async_redis_client,
        strategy_pyd_model=strategy_pyd_model,
        expiry_date=initial_order_pyd_model.expiry,
    )

    logging.info(
        f"[ {crucial_details} ] - Slippage: [ {future_exit_price - signal_pyd_model.future_entry_price_received} points ] introduced for future_exit_price: [ {signal_pyd_model.future_entry_price_received} ] "
    )
    trades_key = f"{signal_pyd_model.strategy_id}"
    exiting_trades_json = await async_redis_client.hget(trades_key, redis_hash)
    exiting_trades_json_list = json.loads(exiting_trades_json)
    logging.info(
        f"[ {kwargs['crucial_details']} ] - Existing total: {len(exiting_trades_json_list)} trades to be closed"
    )
    redis_trade_pyd_model_list = TypeAdapter(List[RedisTradePydModel]).validate_python(
        [json.loads(trade) for trade in exiting_trades_json_list]
    )

    trade_id = redis_trade_pyd_model_list[0].id

    actual_exit_price = updated_order_pyd_model.averageprice
    logging.info(
        f"[ {crucial_details} ], Slippage: [ {signal_pyd_model.future_entry_price_received - actual_exit_price} points ] introduced for future_exit_price: [ {signal_pyd_model.future_entry_price_received} ] "
    )

    updated_data = {}
    total_actual_profit = 0
    total_expected_profit = 0
    for trade_pyd_model in redis_trade_pyd_model_list:
        actual_profit = get_futures_profit(
            entry_price=trade_pyd_model.entry_price,
            exit_price=actual_exit_price,
            quantity=trade_pyd_model.quantity,
            signal=trade_pyd_model.action,
        )

        expected_profit = get_futures_profit(
            entry_price=trade_pyd_model.future_entry_price_received,
            exit_price=signal_pyd_model.future_entry_price_received,
            quantity=trade_pyd_model.quantity,
            signal=trade_pyd_model.action,
        )

        updated_data[trade_pyd_model.id] = {
            "id": trade_pyd_model.id,
            "future_exit_price_received": round(signal_pyd_model.future_entry_price_received, 2),
            "exit_price": actual_exit_price,
            "exit_received_at": signal_pyd_model.received_at,
            "exit_at": datetime.datetime.utcnow(),
            "profit": actual_profit,
            "future_profit": expected_profit,
        }
        total_actual_profit += actual_profit
        total_expected_profit += expected_profit

    await close_trades_in_db_and_remove_from_redis(
        updated_data=updated_data,
        strategy_pyd_model=strategy_pyd_model,
        total_profit=total_actual_profit,
        total_future_profit=total_expected_profit,
        total_redis_trades=len(redis_trade_pyd_model_list),
        async_redis_client=async_redis_client,
        redis_strategy_key_hash=f"{trades_key} {redis_hash}",
        crucial_details=crucial_details,
    )

    async_angelone_client = await get_async_angelone_client(
        async_redis_client=async_redis_client,
        strategy_pyd_model=strategy_pyd_model,
    )
    kwargs["ongoing_profit"] = total_actual_profit
    await task_open_angelone_trade_position(
        **kwargs,
        async_angelone_client=async_angelone_client,
    )
    return trade_id


async def handle_options_entry_order(
    *,
    async_session: AsyncSession,
    async_redis_client: Redis,
    initial_order_pyd_model: InitialOrderPydModel,
    updated_order_pyd_model: UpdatedOrderPydModel,
    strategy_pyd_model: StrategyPydModel,
    crucial_details: str,
):
    trade_pyd_model = OptionsEntryTradePydModel(
        entry_price=updated_order_pyd_model.averageprice,
        future_entry_price=initial_order_pyd_model.future_entry_price_received,
        quantity=(
            updated_order_pyd_model.quantity
            if strategy_pyd_model.position == PositionEnum.LONG
            else -updated_order_pyd_model.quantity
        ),
        entry_at=initial_order_pyd_model.entry_at,
        instrument=updated_order_pyd_model.tradingsymbol,
        entry_received_at=initial_order_pyd_model.entry_received_at,
        received_at=initial_order_pyd_model.entry_received_at,
        expiry=initial_order_pyd_model.expiry,
        action=initial_order_pyd_model.action,
        strategy_id=strategy_pyd_model.id,
        future_entry_price_received=initial_order_pyd_model.future_entry_price_received,
        strike=initial_order_pyd_model.strike,
        option_type=initial_order_pyd_model.option_type,
    )

    trade_db_model = TradeDBModel(
        **trade_pyd_model.model_dump(
            exclude={
                "premium",
                "broker_id",
                "symbol",
                "received_at",
                "future_entry_price",
            },
            exclude_none=True,
        )
    )
    async_session.add(trade_db_model)
    await async_session.flush([trade_db_model])
    msg = f"[ {crucial_details} ] - new trade: [ {trade_db_model.id} ] added to DB"
    logging.info(msg)
    await push_trade_to_redis(
        async_redis_client=async_redis_client,
        trade_db_model=trade_db_model,
        signal_type=initial_order_pyd_model.action,
        crucial_details=crucial_details,
    )
    return trade_db_model.id


async def handle_options_exit_order(
    *,
    async_redis_client: Redis,
    async_httpx_client: AsyncClient,
    initial_order_pyd_model: InitialOrderPydModel,
    updated_order_pyd_model: UpdatedOrderPydModel,
    strategy_pyd_model: StrategyPydModel,
):
    exit_price = updated_order_pyd_model.averageprice
    action = get_action(strategy_pyd_model, initial_order_pyd_model)
    signal_pyd_model = SignalPydModel(
        strategy_id=strategy_pyd_model.id,
        future_entry_price_received=initial_order_pyd_model.future_entry_price_received,
        received_at=datetime.datetime.utcnow(),
        action=action,
    )

    crucial_details = get_crucial_details(
        signal_pyd_model=signal_pyd_model, strategy_pyd_model=strategy_pyd_model
    )
    kwargs, redis_hash = await get_angel_one_pre_trade_kwargs(
        signal_pyd_model=signal_pyd_model,
        strategy_pyd_model=strategy_pyd_model,
        async_redis_client=async_redis_client,
    )
    kwargs["crucial_details"] = crucial_details

    strike_exit_price_dict = {initial_order_pyd_model.strike: exit_price}
    future_exit_price = await get_future_price_from_redis(
        async_redis_client=async_redis_client,
        strategy_pyd_model=strategy_pyd_model,
        expiry_date=kwargs["futures_expiry_date"],
    )

    logging.info(
        f"[ {crucial_details} ] - Slippage: [ {future_exit_price - signal_pyd_model.future_entry_price_received} points ] introduced for future_exit_price: [ {signal_pyd_model.future_entry_price_received} ] "
    )
    trades_key = f"{signal_pyd_model.strategy_id}"
    exiting_trades_json = await async_redis_client.hget(trades_key, redis_hash)
    exiting_trades_json_list = json.loads(exiting_trades_json)
    logging.info(
        f"[ {kwargs['crucial_details']} ] - Existing total: {len(exiting_trades_json_list)} trades to be closed"
    )
    redis_trade_pyd_model_list = TypeAdapter(List[RedisTradePydModel]).validate_python(
        [json.loads(trade) for trade in exiting_trades_json_list]
    )

    trade_id = redis_trade_pyd_model_list[0].id

    updated_data, total_ongoing_profit, total_future_profit = await calculate_profits(
        strike_exit_price_dict=strike_exit_price_dict,
        future_exit_price=future_exit_price,
        signal_pyd_model=signal_pyd_model,
        redis_trade_pyd_model_list=redis_trade_pyd_model_list,
        strategy_pyd_model=strategy_pyd_model,
    )
    logging.info(
        f" [ {crucial_details} ] - adding profit: [ {total_ongoing_profit} ] and future profit: [ {total_future_profit} ]"
    )

    await close_trades_in_db_and_remove_from_redis(
        updated_data=updated_data,
        strategy_pyd_model=strategy_pyd_model,
        total_profit=total_ongoing_profit,
        total_future_profit=total_future_profit,
        total_redis_trades=len(redis_trade_pyd_model_list),
        async_redis_client=async_redis_client,
        redis_strategy_key_hash=f"{trades_key} {redis_hash}",
        crucial_details=crucial_details,
    )

    async_angelone_client = await get_async_angelone_client(
        async_redis_client=async_redis_client,
        strategy_pyd_model=strategy_pyd_model,
    )
    kwargs["ongoing_profit"] = total_ongoing_profit
    await task_open_angelone_trade_position(
        **kwargs,
        async_angelone_client=async_angelone_client,
    )
    return trade_id


async def get_angel_one_pre_trade_kwargs(
    *,
    signal_pyd_model: SignalPydModel,
    strategy_pyd_model: StrategyPydModel,
    async_redis_client: Redis,
) -> tuple[dict[str, Any], str]:
    todays_date = datetime.datetime.utcnow().date()
    kwargs = {
        "signal_pyd_model": signal_pyd_model,
        "strategy_pyd_model": strategy_pyd_model,
        "async_redis_client": async_redis_client,
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
        raise HTTPException(status_code=403, detail="Only on expiry")

    futures_expiry_date = get_expiry_date_to_trade(
        current_expiry_date=current_futures_expiry_date,
        next_expiry_date=next_futures_expiry_date,
        strategy_pyd_model=strategy_pyd_model,
        is_today_expiry=is_today_futures_expiry,
    )

    redis_hash = f"{futures_expiry_date} {PositionEnum.SHORT if signal_pyd_model.action == SignalTypeEnum.BUY else PositionEnum.LONG} {FUT}"
    signal_pyd_model.expiry = futures_expiry_date
    kwargs.update({"futures_expiry_date": futures_expiry_date})

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
        opposite_trade_option_type = get_opposite_trade_option_type(
            strategy_pyd_model.position, signal_pyd_model.action
        )
        redis_hash = f"{options_expiry_date} {opposite_trade_option_type}"
        signal_pyd_model.expiry = options_expiry_date
        kwargs.update({"options_expiry_date": options_expiry_date})

    return kwargs, redis_hash
