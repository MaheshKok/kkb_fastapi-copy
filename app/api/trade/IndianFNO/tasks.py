import asyncio
import json
import logging
import traceback
from datetime import date
from datetime import datetime
from typing import List

import aioredis
from aioredis import Redis
from httpx import AsyncClient
from line_profiler import profile  # noqa
from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy import update

from app.api.trade.IndianFNO.utils import get_angel_one_futures_trading_symbol
from app.api.trade.IndianFNO.utils import get_angel_one_options_trading_symbol
from app.api.trade.IndianFNO.utils import get_future_price
from app.api.trade.IndianFNO.utils import get_future_price_from_redis
from app.api.trade.IndianFNO.utils import get_lots_to_open
from app.api.trade.IndianFNO.utils import get_margin_required
from app.api.trade.IndianFNO.utils import get_strike_and_entry_price
from app.api.trade.IndianFNO.utils import get_strike_and_exit_price_dict
from app.api.trade.IndianFNO.utils import set_quantity
from app.broker.AngelOne import AsyncAngelOneClient
from app.broker.utils import buy_alice_blue_trades
from app.database.models import StrategyModel
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import PositionEnum
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import EntryTradeSchema
from app.schemas.trade import ExitTradeSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.utils.constants import FUT
from app.utils.constants import STRATEGY
from app.utils.constants import update_trade_columns
from app.utils.option_chain import get_option_chain


def calculate_futures_charges(buy_price, sell_price, total_lots):
    # this is exact calculation
    brokerage = 30
    turnover = (buy_price + sell_price) * total_lots
    stt = sell_price * total_lots * 0.0125 / 100
    txn_charge = turnover * 0.0019 / 100
    sebi_charges = turnover * (10 / 10000000)
    investor_pf_charges = sebi_charges
    stamp_duty = buy_price * total_lots * 0.002 / 100
    gst = 0.18 * (brokerage + txn_charge + sebi_charges)
    total_charges = sum(
        [brokerage, stt, txn_charge, sebi_charges, investor_pf_charges, stamp_duty, gst]
    )
    return round(total_charges, 2)


def calculate_options_charges(buy_price, sell_price, total_trades):
    # this is approximate calculations as close as possible
    # Calculate Turnover
    turnover = (buy_price + sell_price) * total_trades
    # Brokerage for buy side and sell side
    brokerage = 15 * 2
    # Transaction charge: 0.053% of the total turnover
    txn_charges = 0.05 / 100 * turnover
    # STT: 0.0125% on sell side
    stt = 0.0625 / 100 * sell_price * total_trades
    # SEBI charges: ₹10 per crore of total turnover
    sebi_charges = 10 / 10000000 * turnover
    # GST: 18% on (brokerage + transaction charges + SEBI charges)
    gst = 0.18 * (brokerage + txn_charges + sebi_charges)
    # Stamp charges: 0.003% on buy side
    stamp_charges = 0.003 / 100 * buy_price * total_trades
    # Calculate total charges
    total_charges = brokerage + stt + txn_charges + sebi_charges + gst + stamp_charges
    return total_charges


def get_options_profit(
    *, entry_price: float, exit_price: float, quantity: int, position: PositionEnum
):
    quantity = abs(quantity)
    total_charges = calculate_options_charges(entry_price, exit_price, quantity)
    if position == PositionEnum.LONG:
        profit = (exit_price - entry_price) * quantity - total_charges
    else:
        profit = (entry_price - exit_price) * quantity - total_charges

    return round(profit, 2)


def get_futures_profit(
    *, entry_price: float, exit_price: float, quantity: int, signal: SignalTypeEnum
):
    quantity = abs(quantity)
    total_charges = calculate_futures_charges(entry_price, exit_price, quantity)
    if signal == SignalTypeEnum.BUY:
        profit = (exit_price - entry_price) * quantity - total_charges
    else:
        profit = (entry_price - exit_price) * quantity - total_charges

    return round(profit, 2)


def construct_update_query(updated_data):
    # First, create a function to generate the CASE clause for a column:
    def generate_case_clause(column_name, data_dict):
        case_clauses = [f"{column_name} = CASE id"]
        for _id, values in data_dict.items():
            value = values.get(column_name)
            if value is None:
                value = "NULL"
            elif column_name in ["exit_received_at", "exit_at"]:
                value = f"'{value}'::TIMESTAMP WITH TIME ZONE"
            else:
                value = f"'{value}'"

            case_clauses.append(f"WHEN '{_id}'::UUID THEN {value}")

        case_clauses.append(f"ELSE {column_name} END")
        return " ".join(case_clauses)

    # Create the SET clauses:
    set_clauses = [generate_case_clause(column, updated_data) for column in update_trade_columns]
    # Extract ids from updated_values:
    ids_str = ",".join(["'{}'".format(_id) for _id in list(updated_data.keys())])
    # Construct the final query:
    query_ = text(
        f"""
              UPDATE trade
              SET
                {", ".join(set_clauses)}
              WHERE id IN ({", ".join([_id + "::UUID" for _id in ids_str.split(",")])})
          """
    )
    return query_


async def calculate_profits(
    *,
    strike_exit_price_dict: dict,
    future_exit_price: float,
    signal_payload_schema: SignalPayloadSchema,
    redis_trade_schema_list: List[RedisTradeSchema],
    strategy_schema: StrategySchema,
):
    updated_data = {}
    total_ongoing_profit = 0
    total_future_profit = 0
    exit_at = datetime.utcnow()
    exit_received_at = signal_payload_schema.received_at
    position = strategy_schema.position
    for redis_trade_schema in redis_trade_schema_list:
        entry_price = redis_trade_schema.entry_price
        quantity = redis_trade_schema.quantity
        exit_price = strike_exit_price_dict.get(redis_trade_schema.strike) or 0.0
        if not exit_price:
            # this is an alarm that exit price is not found for this strike nd this is more likely to happen for broker
            continue

        profit = get_options_profit(
            entry_price=entry_price, exit_price=exit_price, quantity=quantity, position=position
        )
        future_entry_price_received = redis_trade_schema.future_entry_price_received
        future_profit = get_futures_profit(
            entry_price=future_entry_price_received,
            exit_price=future_exit_price,
            quantity=quantity,
            # existing signal when trade was entered into db is captured in action attribute
            signal=redis_trade_schema.action,
        )

        mapping = {
            "id": redis_trade_schema.id,
            "future_exit_price_received": round(
                signal_payload_schema.future_entry_price_received, 2
            ),
            "exit_price": exit_price,
            "exit_received_at": exit_received_at,
            "exit_at": exit_at,
            "profit": profit,
            "future_profit": future_profit,
        }

        updated_data[redis_trade_schema.id] = mapping
        total_ongoing_profit += profit
        total_future_profit += future_profit

    # validate all mappings via ExitTradeSchema
    ExitTradeListValidator = TypeAdapter(List[ExitTradeSchema])
    ExitTradeListValidator.validate_python(list(updated_data.values()))

    return updated_data, round(total_ongoing_profit, 2), round(total_future_profit, 2)


async def push_trade_to_redis(
    *,
    async_redis_client: aioredis.StrictRedis,
    trade_model: TradeModel,
    signal_type: SignalTypeEnum,
    crucial_details: str,
):
    # Add trade to redis, which was earlier taken care by @event.listens_for(TradeModel, "after_insert")
    # it works I confirmed this with python_console with test double data,
    # interesting part is to get such trades I have to call lrange with 0, -1
    redis_key = str(trade_model.strategy_id)
    if trade_model.option_type:
        redis_hash = f"{trade_model.expiry} {trade_model.option_type}"
    else:
        redis_hash = f"{trade_model.expiry} {PositionEnum.LONG if signal_type == SignalTypeEnum.BUY else PositionEnum.SHORT} {FUT}"
    redis_trades_json = await async_redis_client.hget(redis_key, redis_hash)
    new_trade_json = RedisTradeSchema.model_validate(trade_model).model_dump_json(
        exclude={"received_at"}, exclude_none=True
    )
    redis_trades_list = []
    if redis_trades_json:
        redis_trades_list = json.loads(redis_trades_json)
    redis_trades_list.append(new_trade_json)
    await async_redis_client.hset(redis_key, redis_hash, json.dumps(redis_trades_list))
    logging.info(f"[ {crucial_details} ] - new trade: [{trade_model.id}] added to Redis")


async def dump_trade_in_db_and_redis(
    *,
    strategy_schema: StrategySchema,
    entry_price: float,
    signal_payload_schema: SignalPayloadSchema,
    async_redis_client: aioredis.StrictRedis,
    crucial_details: str,
):
    async with Database() as async_session:
        # Use the AsyncSession to perform database operations
        # Example: Create a new entry in the database
        trade_schema = EntryTradeSchema(
            symbol=strategy_schema.symbol,
            entry_price=entry_price,
            entry_received_at=signal_payload_schema.received_at,
            **signal_payload_schema.model_dump(exclude={"premium"}, exclude_none=True),
        )

        trade_model = TradeModel(
            **trade_schema.model_dump(
                exclude={"premium", "broker_id", "symbol", "received_at"},
                exclude_none=True,
            )
        )
        async_session.add(trade_model)
        await async_session.commit()
        logging.info(f"[ {crucial_details} ] - new trade: [{trade_model.id}] added to DB")
        await push_trade_to_redis(
            async_redis_client=async_redis_client,
            trade_model=trade_model,
            signal_type=signal_payload_schema.action,
            crucial_details=crucial_details,
        )


async def close_trades_in_db_and_remove_from_redis(
    *,
    updated_data: dict,
    strategy_schema: StrategySchema,
    total_profit: float,
    total_future_profit: float,
    total_redis_trades: int,
    async_redis_client: aioredis.StrictRedis,
    redis_strategy_key_hash: str,
    crucial_details: str,
):
    async with Database() as async_session:
        query_ = construct_update_query(updated_data)
        await async_session.execute(query_)
        await async_session.flush()

        # rather update strategy_schema funds in redis
        updated_funds = round(strategy_schema.funds + total_profit, 2)
        updated_futures_funds = round(strategy_schema.future_funds + total_future_profit, 2)
        stmt = (
            update(StrategyModel)
            .where(StrategyModel.id == strategy_schema.id)
            .values(funds=updated_funds, future_funds=updated_futures_funds)
        )
        await async_session.execute(stmt)
        await async_session.commit()
        logging.info(
            f"[ {crucial_details} ] - Total Trade : [ {total_redis_trades} ] closed successfully."
        )
        logging.info(
            f"[ {crucial_details} ] - Strategy updated funds: [ {updated_funds} ] and futures funds: [ {updated_futures_funds} ] in db successfully"
        )
        strategy_schema.funds = updated_funds
        strategy_schema.future_funds = updated_futures_funds
        redis_strategy_key = redis_strategy_key_hash.split()[0]
        await async_redis_client.hset(
            redis_strategy_key, STRATEGY, StrategySchema.model_dump_json(strategy_schema)
        )
        logging.info(
            f"[ {crucial_details} ] - Strategy updated funds: [ {updated_funds} ] and futures funds: [ {updated_futures_funds} ] in redis successfully"
        )
        redis_strategy_hash = " ".join(redis_strategy_key_hash.split()[1:])
        result = await async_redis_client.hdel(redis_strategy_key, redis_strategy_hash)
        if result == 1:
            logging.info(
                f"[ {crucial_details} ] - Redis Key: [ {redis_strategy_key_hash} ] deleted from redis successfully"
            )
        else:
            logging.error(
                f"[ {crucial_details} ] - Redis Key: [ {redis_strategy_key_hash} ] not deleted from redis for strategy: [ {strategy_schema.name} ]"
            )


# @profile
async def task_entry_trade(
    *,
    signal_payload_schema: SignalPayloadSchema,
    async_redis_client: aioredis.StrictRedis,
    strategy_schema: StrategySchema,
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
            option_type=signal_payload_schema.option_type,
            strategy_schema=strategy_schema,
        )

        future_entry_price, strike_and_entry_price = await asyncio.gather(
            get_future_price_from_redis(
                async_redis_client=async_redis_client,
                strategy_schema=strategy_schema,
                expiry_date=futures_expiry_date,
            ),
            get_strike_and_entry_price(
                option_chain=option_chain,
                signal_payload_schema=signal_payload_schema,
                strategy_schema=strategy_schema,
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

        signal_payload_schema.strike = strike
        angel_one_trading_symbol = get_angel_one_options_trading_symbol(
            symbol=strategy_schema.symbol,
            expiry_date=signal_payload_schema.expiry,
            strike=int(strike),
            option_type=signal_payload_schema.option_type,
        )
    else:
        if strategy_schema.broker_id:
            entry_price = await buy_alice_blue_trades(
                strike=None,
                signal_payload_schema=signal_payload_schema,
                async_redis_client=async_redis_client,
                strategy_schema=strategy_schema,
                async_httpx_client=async_httpx_client,
            )
            logging.info(
                f"[ {crucial_details} ] - entry price: [ {entry_price} ] from alice blue"
            )
        else:
            entry_price = await get_future_price_from_redis(
                async_redis_client=async_redis_client,
                strategy_schema=strategy_schema,
                expiry_date=futures_expiry_date,
            )
            logging.info(
                f"[ {crucial_details} ] - entry price: [ {entry_price} ] from redis option chain"
            )

        angel_one_trading_symbol = get_angel_one_futures_trading_symbol(
            symbol=strategy_schema.symbol,
            expiry_date=signal_payload_schema.expiry,
        )
        logging.info(
            f"[ {crucial_details} ] - Slippage: [ {entry_price - signal_payload_schema.future_entry_price_received} points ] introduced for future_entry_price: [ {signal_payload_schema.future_entry_price_received} ] "
        )

    margin_for_min_quantity = await get_margin_required(
        client=async_angelone_client,
        price=entry_price,
        signal_type=signal_payload_schema.action,
        strategy_schema=strategy_schema,
        async_redis_client=async_redis_client,
        angel_one_trading_symbol=angel_one_trading_symbol,
        crucial_details=crucial_details,
    )
    lots_to_open = get_lots_to_open(
        strategy_schema=strategy_schema,
        crucial_details=crucial_details,
        ongoing_profit_or_loss=ongoing_profit,
        margin_for_min_quantity=margin_for_min_quantity,
    )
    set_quantity(
        strategy_schema=strategy_schema,
        signal_payload_schema=signal_payload_schema,
        lots_to_open=lots_to_open,
    )

    await dump_trade_in_db_and_redis(
        strategy_schema=strategy_schema,
        entry_price=entry_price,
        signal_payload_schema=signal_payload_schema,
        async_redis_client=async_redis_client,
        crucial_details=crucial_details,
    )

    return "successfully added trade to db"


async def compute_trade_data_needed_for_closing_trade(
    *,
    signal_payload_schema: SignalPayloadSchema,
    redis_trade_schema_list: list[RedisTradeSchema],
    async_redis_client: Redis,
    strategy_schema: StrategySchema,
    async_httpx_client: AsyncClient,
    crucial_details: str,
    futures_expiry_date: date,
    options_expiry_date: date = None,
    only_futures: bool = False,
):
    if only_futures:
        actual_exit_price = await get_future_price(
            async_redis_client=async_redis_client,
            strategy_schema=strategy_schema,
            expiry_date=futures_expiry_date,
            signal_payload_schema=signal_payload_schema,
            async_httpx_client=async_httpx_client,
            redis_trade_schema_list=redis_trade_schema_list,
        )
        logging.info(
            f"[ {crucial_details} ], Slippage: [ {signal_payload_schema.future_entry_price_received - actual_exit_price } points ] introduced for future_exit_price: [ {signal_payload_schema.future_entry_price_received} ] "
        )

        updated_data = {}
        total_actual_profit = 0
        total_expected_profit = 0
        for trade_schema in redis_trade_schema_list:
            actual_profit = get_futures_profit(
                entry_price=trade_schema.entry_price,
                exit_price=actual_exit_price,
                quantity=trade_schema.quantity,
                signal=trade_schema.action,
            )

            expected_profit = get_futures_profit(
                entry_price=trade_schema.future_entry_price_received,
                exit_price=signal_payload_schema.future_entry_price_received,
                quantity=trade_schema.quantity,
                signal=trade_schema.action,
            )

            updated_data[trade_schema.id] = {
                "id": trade_schema.id,
                "future_exit_price_received": round(
                    signal_payload_schema.future_entry_price_received, 2
                ),
                "exit_price": actual_exit_price,
                "exit_received_at": signal_payload_schema.received_at,
                "exit_at": datetime.utcnow(),
                "profit": actual_profit,
                "future_profit": expected_profit,
            }
            total_actual_profit += actual_profit
            total_expected_profit += expected_profit

        return updated_data, total_actual_profit, total_expected_profit
    else:
        strike_exit_price_dict, future_exit_price = await asyncio.gather(
            get_strike_and_exit_price_dict(
                async_redis_client=async_redis_client,
                redis_trade_schema_list=redis_trade_schema_list,
                strategy_schema=strategy_schema,
                async_httpx_client=async_httpx_client,
                expiry_date=options_expiry_date,
            ),
            get_future_price(
                async_redis_client=async_redis_client,
                strategy_schema=strategy_schema,
                expiry_date=futures_expiry_date,
                signal_payload_schema=signal_payload_schema,
                async_httpx_client=async_httpx_client,
            ),
        )
        logging.info(
            f"[ {crucial_details} ] - Slippage: [ {future_exit_price - signal_payload_schema.future_entry_price_received} points ] introduced for future_exit_price: [ {signal_payload_schema.future_entry_price_received} ] "
        )
        updated_data, total_ongoing_profit, total_actual_profit = await calculate_profits(
            strike_exit_price_dict=strike_exit_price_dict,
            future_exit_price=future_exit_price,
            signal_payload_schema=signal_payload_schema,
            redis_trade_schema_list=redis_trade_schema_list,
            strategy_schema=strategy_schema,
        )
        logging.info(
            f" [ {crucial_details} ] - adding profit: [ {total_ongoing_profit} ] and future profit: [ {total_actual_profit} ]"
        )
        return updated_data, total_ongoing_profit, total_actual_profit


async def task_exit_trade(
    *,
    signal_payload_schema: SignalPayloadSchema,
    strategy_schema: StrategySchema,
    async_redis_client: Redis,
    async_httpx_client: AsyncClient,
    only_futures: bool,
    redis_hash: str,
    redis_trade_schema_list: List[RedisTradeSchema],
    crucial_details: str,
    futures_expiry_date: date,
    options_expiry_date: date = None,
):
    trades_key = f"{signal_payload_schema.strategy_id}"

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
            signal_payload_schema=signal_payload_schema,
            redis_trade_schema_list=redis_trade_schema_list,
            async_redis_client=async_redis_client,
            strategy_schema=strategy_schema,
            async_httpx_client=async_httpx_client,
            only_futures=only_futures,
            futures_expiry_date=futures_expiry_date,
            options_expiry_date=options_expiry_date,
            crucial_details=crucial_details,
        )

        # update database with the updated data
        await close_trades_in_db_and_remove_from_redis(
            updated_data=updated_data,
            strategy_schema=strategy_schema,
            total_profit=total_ongoing_profit,
            total_future_profit=total_future_profit,
            total_redis_trades=len(redis_trade_schema_list),
            async_redis_client=async_redis_client,
            redis_strategy_key_hash=f"{trades_key} {redis_hash}",
            crucial_details=crucial_details,
        )
        return total_ongoing_profit

    except Exception as e:
        logging.error(f"[ {crucial_details} ] - Exception while exiting trade: {e}")
        traceback.print_exc()
