import json
import logging
from datetime import datetime

from fastapi_sa.database import db
from line_profiler_pycharm import profile
from sqlalchemy import bindparam
from sqlalchemy import select
from sqlalchemy import update
from tasks.utils import get_future_price
from tasks.utils import get_strike_and_entry_price
from tasks.utils import get_strike_and_exit_price_dict

from app.core.config import get_config
from app.database.base import engine_kw
from app.database.base import get_db_url
from app.database.models import TakeAwayProfit
from app.database.models import TradeModel
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.trade import ExitTradeSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import TradeSchema
from app.services.broker.pya3_alice_blue import buy_alice_blue_trades
from app.utils.constants import Status
from app.utils.option_chain import get_option_chain


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def get_profit(entry_price, exit_price, quantity, position):
    if position == PositionEnum.LONG:
        profit = (exit_price - entry_price) * quantity
    else:
        profit = (entry_price - exit_price) * quantity

    return profit


def init_db(config_file):
    config = get_config(config_file)
    async_db_url = get_db_url(config)
    db.init(async_db_url, engine_kw=engine_kw)


@profile
async def execute_celery_buy_trade_task(
    signal_payload_schema, async_redis, strategy_schema, async_client
):
    option_chain = await get_option_chain(
        async_redis,
        signal_payload_schema.symbol,
        expiry=signal_payload_schema.expiry,
        option_type=signal_payload_schema.option_type,
    )

    strike, entry_price = get_strike_and_entry_price(
        option_chain,
        strike=signal_payload_schema.strike,
        premium=signal_payload_schema.premium,
        future_price=signal_payload_schema.future_entry_price_received,
    )

    # this is very important to set strike to signal_payload_schema as it would be used hereafter
    signal_payload_schema.strike = strike

    # TODO: please remove this when we focus on explicitly buying only futures because strike is Null for futures
    if not strike:
        return None

    if strategy_schema.broker_id:
        status, entry_price = await buy_alice_blue_trades(
            signal_payload_schema, strategy_schema, async_redis, async_client
        )

        if status != Status.COMPLETE:
            # Order not successful so dont make its entry in db
            return None

    future_entry_price = await get_future_price(async_redis, signal_payload_schema.symbol)

    async with db():
        # Use the AsyncSession to perform database operations
        # Example: Create a new entry in the database
        trade_schema = TradeSchema(
            entry_price=entry_price,
            future_entry_price=future_entry_price,
            **signal_payload_schema.dict(exclude={"premium"}),
        )

        trade_model = TradeModel(
            **trade_schema.dict(exclude={"premium", "broker_id", "symbol", "received_at"})
        )
        db.session.add(trade_model)
        await db.session.flush()
        await db.session.refresh(trade_model)
        logging.info(f"{trade_model.id} added to db")
        # Add trade to redis, which was earlier taken care by @event.listens_for(TradeModel, "after_insert")
        # it works i confirmed this with python_console with dummy data,
        # interesting part is to get such trades i have to call lrange with 0, -1
        trade_key = f"{trade_model.strategy_id} {trade_model.expiry} {trade_model.option_type}"
        redis_trade_schema = RedisTradeSchema.from_orm(trade_model).json(exclude={"received_at"})
        await async_redis.rpush(trade_key, redis_trade_schema)
        logging.info(f"{trade_model.id} added to redis")

    return "successfully added trade to db"


async def execute_celery_exit_trade_task(
    signal_payload_schema, redis_ongoing_key, exiting_trades_json, async_redis, strategy_schema
):
    exiting_trades = [json.loads(trade) for trade in json.loads(exiting_trades_json)]

    strike_exit_price_dict = await get_strike_and_exit_price_dict(
        async_redis, signal_payload_schema, exiting_trades, strategy_schema
    )

    future_exit_price = await get_future_price(async_redis, signal_payload_schema.symbol)

    updated_values = []
    total_profit = 0
    total_future_profit = 0

    for trade in exiting_trades:
        entry_price = trade["entry_price"]
        quantity = trade["quantity"]
        position = trade["position"]
        exit_price = strike_exit_price_dict[trade["strike"]]
        profit = get_profit(entry_price, exit_price, quantity, position)

        future_entry_price = trade["future_entry_price"]
        # if option_type is PE then position is SHORT and for CE its LONG
        future_position = (
            PositionEnum.SHORT if trade["option_type"] == OptionTypeEnum.PE else PositionEnum.LONG
        )
        future_profit = get_profit(
            future_entry_price, future_exit_price, quantity, future_position
        )

        mapping = {
            "id": trade["id"],
            "exit_price": exit_price,
            "profit": profit,
            "future_exit_price": future_exit_price,
            "future_profit": future_profit,
            "received_at": signal_payload_schema.received_at,
        }
        exit_trade_schema = ExitTradeSchema(**mapping)
        updated_values.append(exit_trade_schema)
        total_profit += exit_trade_schema.profit
        total_future_profit += exit_trade_schema.future_profit

    async with db():
        fetch_take_away_profit_query_ = await db.session.execute(
            select(TakeAwayProfit).filter_by(strategy_id=trade["strategy_id"])
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()

        if take_away_profit_model:
            take_away_profit_model.profit += total_profit
            take_away_profit_model.future_profit += total_future_profit
            take_away_profit_model.total_trades += len(exiting_trades)
            take_away_profit_model.updated_at = datetime.now()
            await db.session.flush()
        else:
            take_away_profit_model = TakeAwayProfit(
                profit=total_profit,
                future_profit=total_future_profit,
                strategy_id=trade["strategy_id"],
                total_trades=len(exiting_trades),
            )
            db.session.add(take_away_profit_model)
            await db.session.flush()

            # Build a list of update statements for each dictionary in updated_data

        update_stmt = (
            update(TradeModel)
            .where(TradeModel.id == bindparam("_id"))
            .values(
                {
                    "exit_price": bindparam("exit_price"),
                    "profit": bindparam("profit"),
                    "future_exit_price": bindparam("future_exit_price"),
                    "future_profit": bindparam("future_profit"),
                    # received_exit_at is basically received_at
                    "exit_received_at": bindparam("exit_received_at"),
                    "exit_at": bindparam("exit_at"),
                }
            )
        )
        for mapping in updated_values:
            await db.session.execute(
                update_stmt,
                {
                    "_id": mapping.id,
                    "exit_price": mapping.exit_price,
                    "profit": mapping.profit,
                    "future_exit_price": mapping.future_exit_price,
                    "future_profit": mapping.future_profit,
                    "exit_received_at": mapping.exit_received_at,
                    "exit_at": mapping.exit_at,
                },
            )

        await db.session.flush()
        await async_redis.delete(redis_ongoing_key)
    logging.info(
        "successfully closed trades and updated the take_away_profit table with the profit and deleted the redis key"
    )
    return "successfully closed trades and updated the take_away_profit table with the profit and deleted the redis key"
