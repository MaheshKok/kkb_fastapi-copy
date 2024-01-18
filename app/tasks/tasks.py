import asyncio
import json
import logging
from datetime import datetime
from typing import List

import aioredis
from aioredis import Redis
from httpx import AsyncClient
from line_profiler import profile  # noqa
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TakeAwayProfitModel
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import EntryTradeSchema
from app.schemas.trade import ExitTradeSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.tasks.utils import get_future_price
from app.tasks.utils import get_strike_and_entry_price
from app.tasks.utils import get_strike_and_exit_price_dict
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
    total_charges = calculate_options_charges(entry_price, exit_price, quantity)
    if position == PositionEnum.LONG:
        profit = (exit_price - entry_price) * quantity - total_charges
    else:
        profit = (entry_price - exit_price) * quantity - total_charges

    return round(profit, 2)


def get_futures_profit(
    *, entry_price: float, exit_price: float, quantity: int, position: PositionEnum
):
    total_charges = calculate_futures_charges(entry_price, exit_price, quantity)
    if position == PositionEnum.LONG:
        profit = (exit_price - entry_price) * quantity - total_charges
    else:
        profit = (entry_price - exit_price) * quantity - total_charges

    return round(profit, 2)


def construct_update_query(updated_data):
    # First, create a function to generate the CASE clause for a column:
    def generate_case_clause(column_name, data_dict):
        case_clauses = [f"{column_name} = CASE id"]
        for _id, values in data_dict.items():
            if (
                column_name in ["exit_received_at", "exit_at"]
                and values.get(column_name) != "NULL"
            ):
                value = f"'{values.get(column_name)}'::TIMESTAMP WITH TIME ZONE"
            else:
                value = values.get(column_name)
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
    total_profit = 0
    total_future_profit = 0
    exit_at = datetime.utcnow()
    exit_received_at = signal_payload_schema.received_at

    for trade in redis_trade_schema_list:
        entry_price = trade.entry_price
        quantity = trade.quantity
        position = strategy_schema.position
        exit_price = strike_exit_price_dict.get(trade.strike) or 0.0
        if not exit_price:
            # this is an alarm that exit price is not found for this strike nd this is more likely to happen for broker
            continue

        profit = get_options_profit(
            entry_price=entry_price, exit_price=exit_price, quantity=quantity, position=position
        )
        future_entry_price = trade.future_entry_price
        # if option_type is PE then position is SHORT and for CE its LONG
        future_position = (
            PositionEnum.SHORT if trade.option_type == OptionTypeEnum.PE else PositionEnum.LONG
        )
        future_profit = get_futures_profit(
            entry_price=future_entry_price,
            exit_price=future_exit_price,
            quantity=quantity,
            position=future_position,
        )

        mapping = {
            "id": trade.id,
            "exit_price": exit_price,
            "profit": profit,
            "future_exit_price": future_exit_price,
            "future_profit": future_profit,
            "exit_received_at": exit_received_at,
            "exit_at": exit_at,
        }

        updated_data[trade.id] = mapping
        total_profit += profit
        total_future_profit += future_profit

    # validate all mappings via ExitTradeSchema
    ExitTradeListValidator = TypeAdapter(List[ExitTradeSchema])
    ExitTradeListValidator.validate_python(list(updated_data.values()))

    return updated_data, round(total_profit, 2), round(total_future_profit, 2)


async def push_trade_to_redis(
    async_redis_client: aioredis.StrictRedis, trade_model: TradeModel, async_session: AsyncSession
):
    # Add trade to redis, which was earlier taken care by @event.listens_for(TradeModel, "after_insert")
    # it works i confirmed this with python_console with dummy data,
    # interesting part is to get such trades i have to call lrange with 0, -1
    redis_key = str(trade_model.strategy_id)
    redis_hash = f"{trade_model.expiry} {trade_model.option_type}"
    redis_trades_json = await async_redis_client.hget(redis_key, redis_hash)
    new_trade_json = RedisTradeSchema.model_validate(trade_model).model_dump_json(
        exclude={"received_at"}, exclude_none=True
    )
    redis_trades_list = []
    if redis_trades_json:
        redis_trades_list = json.loads(redis_trades_json)
    redis_trades_list.append(new_trade_json)
    await async_redis_client.hset(redis_key, redis_hash, json.dumps(redis_trades_list))
    logging.info(
        f"Strategy: [ {trade_model.strategy_id} ], new trade: [{trade_model.id}] added to Redis"
    )


async def dump_trade_in_db_and_redis(
    *,
    strategy_schema: StrategySchema,
    entry_price: float,
    future_entry_price: float,
    signal_payload_schema: SignalPayloadSchema,
    async_redis_client: aioredis.StrictRedis,
):
    async with Database() as async_session:
        # Use the AsyncSession to perform database operations
        # Example: Create a new entry in the database
        trade_schema = EntryTradeSchema(
            symbol=strategy_schema.symbol,
            entry_price=entry_price,
            future_entry_price=future_entry_price,
            entry_received_at=signal_payload_schema.received_at,
            **signal_payload_schema.model_dump(exclude={"premium", "action"}),
        )

        trade_model = TradeModel(
            **trade_schema.model_dump(
                exclude={"premium", "broker_id", "symbol", "received_at", "action"},
                exclude_none=True,
            )
        )
        async_session.add(trade_model)
        await async_session.commit()
        logging.info(
            f"Strategy: [ {strategy_schema.name} ], new trade: [{trade_model.id}] added to DB"
        )
        await push_trade_to_redis(async_redis_client, trade_model, async_session)


async def close_trades_in_db_and_remove_from_redis(
    *,
    updated_data: dict,
    strategy_schema: StrategySchema,
    total_profit: float,
    total_future_profit: float,
    total_redis_trades: int,
    async_redis_client: aioredis.StrictRedis,
    redis_strategy_key_hash: str,
):
    async with Database() as async_session:
        query_ = construct_update_query(updated_data)
        await async_session.execute(query_)
        await async_session.flush()

        fetch_take_away_profit_query_ = await async_session.execute(
            select(TakeAwayProfitModel).filter_by(strategy_id=strategy_schema.id)
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()

        if take_away_profit_model:
            take_away_profit_model.profit += total_profit
            take_away_profit_model.future_profit += total_future_profit
            take_away_profit_model.total_trades += total_redis_trades
            take_away_profit_model.updated_at = datetime.now()
        else:
            take_away_profit_model = TakeAwayProfitModel(
                profit=total_profit,
                future_profit=total_future_profit,
                strategy_id=strategy_schema.id,
                total_trades=total_redis_trades,
            )
            async_session.add(take_away_profit_model)

        await async_session.commit()
        logging.info(
            f"Total Trade: [ {total_redis_trades} ] closed successfully for strategy: [ {strategy_schema.name} ]"
        )
        redis_strategy_key = redis_strategy_key_hash.split()[0]
        redis_strategy_hash = " ".join(redis_strategy_key_hash.split()[1:])
        result = await async_redis_client.hdel(redis_strategy_key, redis_strategy_hash)
        if result == 1:
            logging.info(
                f"Redis Key: [ {redis_strategy_key_hash} ] deleted from redis successfully for strategy: [ {strategy_schema.name} ]"
            )
        else:
            logging.error(
                f"Redis Key: [ {redis_strategy_key_hash} ] not deleted from redis for strategy: [ {strategy_schema.name} ]"
            )


# @profile
async def task_entry_trade(
    *,
    signal_payload_schema: SignalPayloadSchema,
    async_redis_client: aioredis.StrictRedis,
    strategy_schema: StrategySchema,
    async_httpx_client: AsyncClient,
    only_futures: bool = False,
):
    if only_futures:
        future_entry_price = await get_future_price(
            async_redis_client=async_redis_client,
            strategy_schema=strategy_schema,
        )
        logging.info(
            f"Strategy: [ {strategy_schema.name} ], new trade with future entry price: [ {future_entry_price} ] entering into db"
        )
        logging.info(
            f"Strategy: [ {strategy_schema.name} ], Slippage: [ {future_entry_price - signal_payload_schema.future_entry_price_received} points ] introduced for future_entry_price: [ {signal_payload_schema.future_entry_price_received} ] "
        )

        await dump_trade_in_db_and_redis(
            entry_price=0.0,
            strategy_schema=strategy_schema,
            future_entry_price=future_entry_price,
            signal_payload_schema=signal_payload_schema,
            async_redis_client=async_redis_client,
        )

        return "successfully added trade to db"

    else:
        option_chain = await get_option_chain(
            async_redis_client=async_redis_client,
            expiry=signal_payload_schema.expiry,
            option_type=signal_payload_schema.option_type,
            strategy_schema=strategy_schema,
        )

        strike_and_entry_price, future_entry_price = await asyncio.gather(
            get_strike_and_entry_price(
                option_chain=option_chain,
                signal_payload_schema=signal_payload_schema,
                strategy_schema=strategy_schema,
                async_redis_client=async_redis_client,
                async_httpx_client=async_httpx_client,
            ),
            get_future_price(
                async_redis_client=async_redis_client,
                strategy_schema=strategy_schema,
            ),
        )

        strike, entry_price = strike_and_entry_price

        # TODO: please remove this when we focus on explicitly buying only futures because strike is Null for futures
        if not strike:
            logging.info(
                f"Strategy: [ {strategy_schema.name} ], skipping entry of new tradde as strike is Null: {entry_price}"
            )
            return None

        logging.info(
            f"Strategy: [ {strategy_schema.name} ], new trade with strike: [ {strike} ] and entry price: [ {entry_price} ] entering into db"
        )
        logging.info(
            f"Strategy: [ {strategy_schema.name} ], Slippage: [ {future_entry_price - signal_payload_schema.future_entry_price_received} points ] introduced for future_entry_price: [ {signal_payload_schema.future_entry_price_received} ] "
        )

        # this is very important to set strike to signal_payload_schema as it would be used hereafter
        signal_payload_schema.strike = strike

        await dump_trade_in_db_and_redis(
            strategy_schema=strategy_schema,
            entry_price=entry_price,
            future_entry_price=future_entry_price,
            signal_payload_schema=signal_payload_schema,
            async_redis_client=async_redis_client,
        )

        return "successfully added trade to db"


async def compute_trade_data_needed_for_closing_trade(
    *,
    signal_payload_schema: SignalPayloadSchema,
    redis_trade_schema_list: list[RedisTradeSchema],
    async_redis_client: Redis,
    strategy_schema: StrategySchema,
    async_httpx_client: AsyncClient,
    only_futures: bool = False,
):
    if only_futures:
        future_exit_price = await get_future_price(
            async_redis_client=async_redis_client,
            strategy_schema=strategy_schema,
        )
        logging.info(
            f"Strategy: [ {strategy_schema.name} ], Slippage: [ {future_exit_price - signal_payload_schema.future_entry_price_received} points ] introduced for future_exit_price: [ {signal_payload_schema.future_entry_price_received} ] "
        )

        trade_schema = redis_trade_schema_list[0]
        future_position = (
            PositionEnum.SHORT
            if trade_schema.option_type == OptionTypeEnum.PE
            else PositionEnum.LONG
        )
        future_profit = get_futures_profit(
            entry_price=trade_schema.future_entry_price,
            exit_price=future_exit_price,
            quantity=trade_schema.quantity,
            position=future_position,
        )

        updated_data = {
            trade_schema.id: {
                "id": trade_schema.id,
                "future_exit_price": future_exit_price,
                "future_profit": future_profit,
                "exit_received_at": signal_payload_schema.received_at,
                "exit_at": datetime.utcnow(),
            }
        }
        return updated_data, 0.0, future_profit
    else:
        strike_exit_price_dict, future_exit_price = await asyncio.gather(
            get_strike_and_exit_price_dict(
                async_redis_client=async_redis_client,
                signal_payload_schema=signal_payload_schema,
                redis_trade_schema_list=redis_trade_schema_list,
                strategy_schema=strategy_schema,
                async_httpx_client=async_httpx_client,
            ),
            get_future_price(
                async_redis_client=async_redis_client,
                strategy_schema=strategy_schema,
            ),
        )
        logging.info(
            f"Strategy: [ {strategy_schema.name} ], Slippage: [ {future_exit_price - signal_payload_schema.future_entry_price_received} points ] introduced for future_exit_price: [ {signal_payload_schema.future_entry_price_received} ] "
        )
        updated_data, total_profit, total_future_profit = await calculate_profits(
            strike_exit_price_dict=strike_exit_price_dict,
            future_exit_price=future_exit_price,
            signal_payload_schema=signal_payload_schema,
            redis_trade_schema_list=redis_trade_schema_list,
            strategy_schema=strategy_schema,
        )
        logging.info(
            f"Strategy: [ {strategy_schema.name} ], adding profit: [ {total_profit} ] and future profit: [ {total_future_profit} ]"
        )
        return updated_data, total_profit, total_future_profit


# @profile
async def task_exit_trade(
    *,
    signal_payload_schema: SignalPayloadSchema,
    redis_strategy_key_hash: str,
    redis_trade_schema_list: list[RedisTradeSchema],
    async_redis_client: Redis,
    strategy_schema: StrategySchema,
    async_httpx_client: AsyncClient,
):
    only_futures = True if strategy_schema.instrument_type == InstrumentTypeEnum.FUTIDX else False

    (
        updated_data,
        total_profit,
        total_future_profit,
    ) = await compute_trade_data_needed_for_closing_trade(
        signal_payload_schema=signal_payload_schema,
        redis_trade_schema_list=redis_trade_schema_list,
        async_redis_client=async_redis_client,
        strategy_schema=strategy_schema,
        async_httpx_client=async_httpx_client,
        only_futures=only_futures,
    )

    # update database with the updated data
    await close_trades_in_db_and_remove_from_redis(
        updated_data=updated_data,
        strategy_schema=strategy_schema,
        total_profit=total_profit,
        total_future_profit=total_future_profit,
        total_redis_trades=len(redis_trade_schema_list),
        async_redis_client=async_redis_client,
        redis_strategy_key_hash=redis_strategy_key_hash,
    )

    return f"{redis_strategy_key_hash} closed trades, updated the take_away_profit with the profit and deleted the redis key"
