import asyncio
import logging
import traceback
from datetime import date
from typing import List

import aioredis
from aioredis import Redis
from httpx import AsyncClient
from line_profiler import profile  # noqa

from app.api.trade.indian_fno.alice_blue.utils import buy_alice_blue_trades
from app.api.trade.indian_fno.utils import close_trades_in_db_and_remove_from_redis
from app.api.trade.indian_fno.utils import compute_trade_data_needed_for_closing_trade
from app.api.trade.indian_fno.utils import dump_trade_in_db_and_redis
from app.api.trade.indian_fno.utils import get_angel_one_futures_trading_symbol
from app.api.trade.indian_fno.utils import get_angel_one_options_trading_symbol
from app.api.trade.indian_fno.utils import get_future_price_from_redis
from app.api.trade.indian_fno.utils import get_lots_to_open
from app.api.trade.indian_fno.utils import get_margin_required
from app.api.trade.indian_fno.utils import get_strike_and_entry_price
from app.api.trade.indian_fno.utils import set_quantity
from app.broker_clients.async_angel_one import AsyncAngelOneClient
from app.pydantic_models.strategy import StrategyPydanticModel
from app.pydantic_models.trade import RedisTradePydanticModel
from app.pydantic_models.trade import SignalPydanticModel
from app.utils.option_chain import get_option_chain


# @profile
async def task_entry_trade(
    *,
    signal_pyd_model: SignalPydanticModel,
    async_redis_client: aioredis.StrictRedis,
    strategy_pyd_model: StrategyPydanticModel,
    async_httpx_client: AsyncClient,
    crucial_details: str,
    async_angelone_client: AsyncAngelOneClient,
    futures_expiry_date: date,
    options_expiry_date: date = None,
    only_futures: bool = False,
    ongoing_profit: int = 0,
):
    if not only_futures:
        option_chain = await get_option_chain(
            async_redis_client=async_redis_client,
            expiry=options_expiry_date,
            option_type=signal_pyd_model.option_type,
            strategy_pyd_model=strategy_pyd_model,
        )

        future_entry_price, strike_and_entry_price = await asyncio.gather(
            get_future_price_from_redis(
                async_redis_client=async_redis_client,
                strategy_pyd_model=strategy_pyd_model,
                expiry_date=futures_expiry_date,
            ),
            get_strike_and_entry_price(
                option_chain=option_chain,
                signal_pyd_model=signal_pyd_model,
                strategy_pyd_model=strategy_pyd_model,
                async_redis_client=async_redis_client,
                async_httpx_client=async_httpx_client,
                crucial_details=crucial_details,
            ),
        )
        logging.info(
            f"[ {crucial_details} ] - new trade with future entry price : [ {future_entry_price} ] fetched from redis entering into db"
        )

        strike, entry_price = strike_and_entry_price
        if not strike:
            logging.info(
                f"[ {crucial_details} ] - skipping entry of new tradde as strike is Null: {entry_price}"
            )
            return None

        signal_pyd_model.strike = strike
        angel_one_trading_symbol = get_angel_one_options_trading_symbol(
            symbol=strategy_pyd_model.symbol,
            expiry_date=signal_pyd_model.expiry,
            strike=int(strike),
            option_type=signal_pyd_model.option_type,
        )
    else:
        if strategy_pyd_model.broker_id:
            entry_price = await buy_alice_blue_trades(
                strike=None,
                signal_pyd_model=signal_pyd_model,
                async_redis_client=async_redis_client,
                strategy_pyd_model=strategy_pyd_model,
                async_httpx_client=async_httpx_client,
            )
            logging.info(
                f"[ {crucial_details} ] - entry price: [ {entry_price} ] from alice blue"
            )
        else:
            entry_price = await get_future_price_from_redis(
                async_redis_client=async_redis_client,
                strategy_pyd_model=strategy_pyd_model,
                expiry_date=futures_expiry_date,
            )
            logging.info(
                f"[ {crucial_details} ] - entry price: [ {entry_price} ] from redis option chain"
            )

        angel_one_trading_symbol = get_angel_one_futures_trading_symbol(
            symbol=strategy_pyd_model.symbol,
            expiry_date=signal_pyd_model.expiry,
        )
        logging.info(
            f"[ {crucial_details} ] - Slippage: [ {entry_price - signal_pyd_model.future_entry_price_received} points ] introduced for future_entry_price: [ {signal_pyd_model.future_entry_price_received} ] "
        )

    margin_for_min_quantity = await get_margin_required(
        client=async_angelone_client,
        price=entry_price,
        signal_type=signal_pyd_model.action,
        strategy_pyd_model=strategy_pyd_model,
        async_redis_client=async_redis_client,
        angel_one_trading_symbol=angel_one_trading_symbol,
        crucial_details=crucial_details,
    )
    lots_to_open = get_lots_to_open(
        strategy_pyd_model=strategy_pyd_model,
        crucial_details=crucial_details,
        ongoing_profit_or_loss=ongoing_profit,
        margin_for_min_quantity=margin_for_min_quantity,
    )
    set_quantity(
        strategy_pyd_model=strategy_pyd_model,
        signal_pyd_model=signal_pyd_model,
        lots_to_open=lots_to_open,
    )

    await dump_trade_in_db_and_redis(
        strategy_pyd_model=strategy_pyd_model,
        entry_price=entry_price,
        signal_pyd_model=signal_pyd_model,
        async_redis_client=async_redis_client,
        crucial_details=crucial_details,
    )

    return "successfully added trade to db"


async def task_exit_trade(
    *,
    signal_pyd_model: SignalPydanticModel,
    strategy_pyd_model: StrategyPydanticModel,
    async_redis_client: Redis,
    async_httpx_client: AsyncClient,
    only_futures: bool,
    redis_hash: str,
    redis_trade_pyd_model_list: List[RedisTradePydanticModel],
    crucial_details: str,
    futures_expiry_date: date,
    options_expiry_date: date = None,
):
    trades_key = f"{signal_pyd_model.strategy_id}"

    # TODO: in future decide based on strategy new column, strategy_type:
    # if strategy_position is "every" then close all ongoing trades and buy new trade
    # 2. strategy_position is "signal", then on action: EXIT, close same option type trades
    # and buy new trade on BUY action,
    # To be decided in future, the name of actions

    try:
        (
            updated_data,
            total_ongoing_profit,
            total_future_profit,
        ) = await compute_trade_data_needed_for_closing_trade(
            signal_pyd_model=signal_pyd_model,
            redis_trade_pyd_model_list=redis_trade_pyd_model_list,
            async_redis_client=async_redis_client,
            strategy_pyd_model=strategy_pyd_model,
            async_httpx_client=async_httpx_client,
            only_futures=only_futures,
            futures_expiry_date=futures_expiry_date,
            options_expiry_date=options_expiry_date,
            crucial_details=crucial_details,
        )

        # update database with the updated data
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
        return total_ongoing_profit

    except Exception as e:
        logging.error(f"[ {crucial_details} ] - Exception while exiting trade: {e}")
        traceback.print_exc()
