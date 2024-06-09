import logging
import traceback
from datetime import date
from typing import List

import aioredis
from aioredis import Redis
from httpx import AsyncClient

from app.api.trade.indian_fno.angel_one.db_operations import dump_angel_one_order_in_db
from app.api.trade.indian_fno.angel_one.trading_operations import create_angel_one_order
from app.api.trade.indian_fno.utils import get_angel_one_futures_trading_symbol
from app.api.trade.indian_fno.utils import get_angel_one_options_trading_symbol
from app.api.trade.indian_fno.utils import get_lots_to_open
from app.api.trade.indian_fno.utils import get_margin_required
from app.api.trade.indian_fno.utils import get_strike_and_entry_price_from_option_chain
from app.api.trade.indian_fno.utils import is_buy_signal
from app.api.trade.indian_fno.utils import is_futures_strategy
from app.api.trade.indian_fno.utils import is_short_sell_strategy
from app.api.trade.indian_fno.utils import set_quantity
from app.broker_clients.async_angel_one import AsyncAngelOneClient
from app.pydantic_models.angel_one import TransactionTypeEnum
from app.pydantic_models.strategy import StrategyPydModel
from app.pydantic_models.trade import RedisTradePydModel
from app.pydantic_models.trade import SignalPydModel
from app.utils.option_chain import get_option_chain


async def handle_futures_trade(
    *,
    signal_pyd_model: SignalPydModel,
    async_redis_client: Redis,
    strategy_pyd_model: StrategyPydModel,
    crucial_details: str,
    async_angelone_client: AsyncAngelOneClient,
    ongoing_profit: int,
) -> str:
    """
    Handles the opening of a futures trade with Angel One.
    """
    angel_one_trading_symbol = get_angel_one_futures_trading_symbol(
        symbol=strategy_pyd_model.symbol,
        expiry_date=signal_pyd_model.expiry,
    )

    entry_price = signal_pyd_model.future_entry_price_received

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

    if is_short_sell_strategy(strategy_pyd_model):
        transaction_type = TransactionTypeEnum.SELL
    else:
        transaction_type = TransactionTypeEnum.BUY

    order_response_pyd_model = await create_angel_one_order(
        async_angelone_client=async_angelone_client,
        async_redis_client=async_redis_client,
        strategy_pyd_model=strategy_pyd_model,
        is_fut=True,
        expiry_date=signal_pyd_model.expiry,
        crucial_details=crucial_details,
        transaction_type=transaction_type,
        quantity=lots_to_open,
    )

    await dump_angel_one_order_in_db(
        order_data_pyd_model=order_response_pyd_model.data,
        strategy_pyd_model=strategy_pyd_model,
        signal_pyd_model=signal_pyd_model,
        crucial_details=crucial_details,
        entry_exit="ENTRY",
    )
    return "successfully added trade to db"


async def handle_options_trade(
    *,
    signal_pyd_model: SignalPydModel,
    async_redis_client: Redis,
    strategy_pyd_model: StrategyPydModel,
    crucial_details: str,
    async_angelone_client: AsyncAngelOneClient,
    options_expiry_date: date,
    ongoing_profit: int,
) -> str:
    """
    Handles the opening of an options trade with Angel One.
    """
    option_chain = await get_option_chain(
        async_redis_client=async_redis_client,
        expiry=options_expiry_date,
        option_type=signal_pyd_model.option_type,
        strategy_pyd_model=strategy_pyd_model,
        is_future=False,
    )

    strike_and_entry_price = await (
        get_strike_and_entry_price_from_option_chain(
            option_chain=option_chain,
            signal_pyd_model=signal_pyd_model,
            premium=strategy_pyd_model.premium,
        ),
    )

    strike, entry_price = strike_and_entry_price

    angel_one_trading_symbol = get_angel_one_options_trading_symbol(
        symbol=strategy_pyd_model.symbol,
        expiry_date=signal_pyd_model.expiry,
        option_type=signal_pyd_model.option_type,
        strike=strike,
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

    if is_short_sell_strategy(strategy_pyd_model):
        transaction_type = TransactionTypeEnum.SELL
    else:
        transaction_type = TransactionTypeEnum.BUY

    order_response_pyd_model = await create_angel_one_order(
        async_angelone_client=async_angelone_client,
        async_redis_client=async_redis_client,
        strategy_pyd_model=strategy_pyd_model,
        is_fut=False,
        expiry_date=signal_pyd_model.expiry,
        option_type=signal_pyd_model.option_type,
        crucial_details=crucial_details,
        strike=strike,
        transaction_type=transaction_type,
        quantity=lots_to_open,
    )
    await dump_angel_one_order_in_db(
        order_data_pyd_model=order_response_pyd_model.data,
        strategy_pyd_model=strategy_pyd_model,
        signal_pyd_model=signal_pyd_model,
        crucial_details=crucial_details,
        entry_exit="ENTRY",
    )
    return "successfully added trade to db"


# @profile
async def task_open_angelone_trade_position(
    *,
    signal_pyd_model: SignalPydModel,
    async_redis_client: aioredis.StrictRedis,
    strategy_pyd_model: StrategyPydModel,
    async_httpx_client: AsyncClient,
    crucial_details: str,
    async_angelone_client: AsyncAngelOneClient,
    futures_expiry_date: date,
    options_expiry_date: date = None,
    only_futures: bool = False,
    ongoing_profit: int = 0,
):
    if only_futures:
        return await handle_futures_trade(
            signal_pyd_model=signal_pyd_model,
            async_redis_client=async_redis_client,
            strategy_pyd_model=strategy_pyd_model,
            crucial_details=crucial_details,
            async_angelone_client=async_angelone_client,
            ongoing_profit=ongoing_profit,
        )
    else:
        return await handle_options_trade(
            signal_pyd_model=signal_pyd_model,
            async_redis_client=async_redis_client,
            strategy_pyd_model=strategy_pyd_model,
            crucial_details=crucial_details,
            async_angelone_client=async_angelone_client,
            options_expiry_date=options_expiry_date,
            ongoing_profit=ongoing_profit,
        )


async def task_exit_angelone_trade_position(
    *,
    signal_pyd_model: SignalPydModel,
    strategy_pyd_model: StrategyPydModel,
    async_redis_client: Redis,
    redis_trade_pyd_model_list: List[RedisTradePydModel],
    async_angelone_client: AsyncAngelOneClient,
    crucial_details: str,
):
    # TODO: in future decide based on strategy new column, strategy_type:
    # if strategy_position is "every" then close all ongoing trades and buy new trade
    # 2. strategy_position is "signal", then on action: EXIT, close same option type trades
    # and buy new trade on BUY action,
    # To be decided in future, the name of actions

    expiry_date = redis_trade_pyd_model_list[0].expiry

    try:
        if is_futures_strategy(strategy_pyd_model):
            transaction_type = signal_pyd_model.action.upper()
            lots_to_open = sum(
                redis_trade_pyd_model.quantity
                for redis_trade_pyd_model in redis_trade_pyd_model_list
            )
            order_response_pyd_model = await create_angel_one_order(
                async_angelone_client=async_angelone_client,
                async_redis_client=async_redis_client,
                strategy_pyd_model=strategy_pyd_model,
                is_fut=True,
                expiry_date=expiry_date,
                crucial_details=crucial_details,
                transaction_type=transaction_type,
                quantity=lots_to_open,
            )

            await dump_angel_one_order_in_db(
                order_data_pyd_model=order_response_pyd_model.data,
                strategy_pyd_model=strategy_pyd_model,
                signal_pyd_model=signal_pyd_model,
                crucial_details=crucial_details,
                entry_exit="EXIT",
            )
        else:
            """
            if current_signal is BUY:
                if strategy is SHORT_SELL:
                    if earlier_signal was SELL:
                        # We had previously sold a Call Option (CE)
                        # To exit this position, we need to buy back the Call Option (CE)
                        exit_position = buy CE
                elif strategy is LONG:
                    if earlier_signal was SELL:
                        # We had previously bought a Put Option (PE)
                        # To exit this position, we need to sell the Put Option (PE)
                        exit_position = sell PE
            """
            if is_short_sell_strategy(strategy_pyd_model):
                transaction_type = signal_pyd_model.action.upper()
            else:
                if is_buy_signal(signal_pyd_model):
                    transaction_type = TransactionTypeEnum.SELL
                else:
                    transaction_type = TransactionTypeEnum.BUY

            strike_option_type_mappings = {}
            for trade in redis_trade_pyd_model_list:
                key = f"{trade.strike}_{trade.option_type}"
                if key in strike_option_type_mappings:
                    strike_option_type_mappings[key] = (
                        strike_option_type_mappings[key] + trade.quantity
                    )
                else:
                    strike_option_type_mappings[
                        f"{trade.strike}_{trade.option_type}"
                    ] = trade.quantity

            # TODO: how to figure out how many trades are closed and at what price,
            # we get tradingsymbol in webhook updated order which is enough
            for strike_option_type, quantity in strike_option_type_mappings.items():
                strike, option_type = strike_option_type.split("_")
                order_response_pyd_model = await create_angel_one_order(
                    async_angelone_client=async_angelone_client,
                    async_redis_client=async_redis_client,
                    strategy_pyd_model=strategy_pyd_model,
                    is_fut=False,
                    expiry_date=expiry_date,
                    crucial_details=crucial_details,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    strike=strike,
                    option_type=option_type,
                )

                await dump_angel_one_order_in_db(
                    order_data_pyd_model=order_response_pyd_model.data,
                    strategy_pyd_model=strategy_pyd_model,
                    signal_pyd_model=signal_pyd_model,
                    crucial_details=crucial_details,
                    entry_exit="EXIT",
                )
    except Exception as e:
        logging.error(
            f"[ {crucial_details} ] - Exception while placing angel one exit trade: {e}"
        )
        traceback.print_exc()
