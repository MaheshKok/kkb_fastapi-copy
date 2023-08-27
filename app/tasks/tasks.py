import logging
from datetime import datetime
from typing import List

from aioredis import Redis
from httpx import AsyncClient
from line_profiler import profile  # noqa
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy import text

from app.database.models import TakeAwayProfitModel
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
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
from app.utils.option_chain import get_option_chain


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


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


def get_options_profit(entry_price, exit_price, quantity, position):
    total_charges = calculate_options_charges(entry_price, exit_price, quantity)
    if position == PositionEnum.LONG:
        profit = (exit_price - entry_price) * quantity - total_charges
    else:
        profit = (entry_price - exit_price) * quantity - total_charges

    return round(profit, 2)


def get_futures_profit(entry_price, exit_price, quantity, position):
    total_charges = calculate_futures_charges(entry_price, exit_price, quantity)
    if position == PositionEnum.LONG:
        profit = (exit_price - entry_price) * quantity - total_charges
    else:
        profit = (entry_price - exit_price) * quantity - total_charges

    return round(profit, 2)


# @profile
async def task_entry_trade(
    *, signal_payload_schema, async_redis_client, strategy_schema, async_httpx_client
):
    option_chain = await get_option_chain(
        async_redis_client=async_redis_client,
        expiry=signal_payload_schema.expiry,
        option_type=signal_payload_schema.option_type,
        strategy_schema=strategy_schema,
    )

    strike, entry_price = await get_strike_and_entry_price(
        option_chain=option_chain,
        signal_payload_schema=signal_payload_schema,
        strategy_schema=strategy_schema,
        async_redis_client=async_redis_client,
        async_httpx_client=async_httpx_client,
    )

    # this is very important to set strike to signal_payload_schema as it would be used hereafter
    signal_payload_schema.strike = strike

    # TODO: please remove this when we focus on explicitly buying only futures because strike is Null for futures
    if not strike:
        return None

    future_entry_price = await get_future_price(
        async_redis_client=async_redis_client,
        strategy_schema=strategy_schema,
    )

    async with Database() as async_session:
        # Use the AsyncSession to perform database operations
        # Example: Create a new entry in the database
        trade_schema = EntryTradeSchema(
            symbol=strategy_schema.symbol,
            entry_price=entry_price,
            future_entry_price=future_entry_price,
            entry_received_at=signal_payload_schema.received_at,
            **signal_payload_schema.model_dump(exclude={"premium"}),
        )

        trade_model = TradeModel(
            **trade_schema.model_dump(exclude={"premium", "broker_id", "symbol", "received_at"})
        )
        async_session.add(trade_model)
        await async_session.commit()
        # Add trade to redis, which was earlier taken care by @event.listens_for(TradeModel, "after_insert")
        # it works i confirmed this with python_console with dummy data,
        # interesting part is to get such trades i have to call lrange with 0, -1
        trade_key = f"{trade_model.strategy_id} {trade_model.expiry} {trade_model.option_type}"
        redis_trade_json = RedisTradeSchema.model_validate(trade_model).model_dump_json(
            exclude={"received_at"}
        )
        await async_redis_client.rpush(trade_key, redis_trade_json)
        logging.info(f"{trade_model.id} added to db and redis")

    return "successfully added trade to db"


# @profile
async def task_exit_trade(
    *,
    signal_payload_schema: SignalPayloadSchema,
    redis_ongoing_key: str,
    redis_trade_schema_list: list[RedisTradeSchema],
    async_redis_client: Redis,
    strategy_schema: StrategySchema,
    async_httpx_client: AsyncClient,
):
    strike_exit_price_dict = await get_strike_and_exit_price_dict(
        async_redis_client=async_redis_client,
        signal_payload_schema=signal_payload_schema,
        redis_trade_schema_list=redis_trade_schema_list,
        strategy_schema=strategy_schema,
        async_httpx_client=async_httpx_client,
    )

    future_exit_price = await get_future_price(
        async_redis_client=async_redis_client,
        strategy_schema=strategy_schema,
    )

    updated_data = {}
    total_profit = 0
    total_future_profit = 0

    for trade in redis_trade_schema_list:
        entry_price = float(trade.entry_price)
        quantity = trade.quantity
        position = trade.position
        exit_price = strike_exit_price_dict.get(trade.strike) or 0.0
        if not exit_price:
            # this is an alarm that exit price is not found for this strike nd this is more likely to happen for broker
            continue

        profit = get_options_profit(entry_price, exit_price, quantity, position)
        future_entry_price = float(trade.future_entry_price)
        # if option_type is PE then position is SHORT and for CE its LONG
        future_position = (
            PositionEnum.SHORT if trade.option_type == OptionTypeEnum.PE else PositionEnum.LONG
        )
        future_profit = get_futures_profit(
            future_entry_price, future_exit_price, quantity, future_position
        )

        mapping = {
            "id": trade.id,
            "exit_price": exit_price,
            "profit": profit,
            "future_exit_price": future_exit_price,
            "future_profit": future_profit,
            "exit_received_at": str(signal_payload_schema.received_at),
        }
        updated_data[trade.id] = mapping
        total_profit += profit
        total_future_profit += future_profit

    # validate all mappings via ExitTradeSchema
    ExitTradeListValidator = TypeAdapter(List[ExitTradeSchema])
    ExitTradeListValidator.validate_python(list(updated_data.values()))

    total_profit = float(total_profit)
    total_future_profit = float(total_future_profit)
    async with Database() as async_session:
        # First, create a function to generate the CASE clause for a column:
        def generate_case_clause(column_name, data_dict):
            case_clauses = [f"{column_name} = CASE id"]
            for id, values in data_dict.items():
                if column_name == "exit_received_at" and values.get(column_name) != "NULL":
                    value = f"'{values.get(column_name)}'::TIMESTAMP WITH TIME ZONE"
                else:
                    value = values.get(column_name)
                case_clauses.append(f"WHEN '{id}'::UUID THEN {value}")
            case_clauses.append(f"ELSE {column_name} END")
            return " ".join(case_clauses)

        # Create the SET clauses:
        set_clauses = []
        columns = [
            "exit_price",
            "profit",
            "future_exit_price",
            "future_profit",
            "exit_received_at",
        ]
        for column in columns:
            set_clauses.append(generate_case_clause(column, updated_data))

        # Extract ids from updated_values:
        ids_list = list(updated_data.keys())
        ids_str = ",".join(["'{}'".format(id) for id in ids_list])
        # Construct the final query:
        query = text(
            f"""
            UPDATE trade
            SET
              {", ".join(set_clauses)}
            WHERE id IN ({", ".join([id + "::UUID" for id in ids_str.split(",")])})
        """
        )

        await async_session.execute(query)
        await async_session.flush()

        fetch_take_away_profit_query_ = await async_session.execute(
            select(TakeAwayProfitModel).filter_by(strategy_id=strategy_schema.id)
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()

        if take_away_profit_model:
            take_away_profit_model.profit += total_profit
            take_away_profit_model.future_profit += total_future_profit
            take_away_profit_model.total_trades += len(redis_trade_schema_list)
            take_away_profit_model.updated_at = datetime.now()
        else:
            take_away_profit_model = TakeAwayProfitModel(
                profit=total_profit,
                future_profit=total_future_profit,
                strategy_id=strategy_schema.id,
                total_trades=len(redis_trade_schema_list),
            )
            async_session.add(take_away_profit_model)

        await async_session.commit()
        await async_redis_client.delete(redis_ongoing_key)
    logging.info(
        f"{redis_ongoing_key} closed trades, updated the take_away_profit with the profit and deleted the redis key"
    )
    return f"{redis_ongoing_key} closed trades, updated the take_away_profit with the profit and deleted the redis key"
