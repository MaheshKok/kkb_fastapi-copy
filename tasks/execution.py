import json
import logging
from datetime import datetime

from fastapi_sa.database import db
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
from app.extensions.redis_cache.utils import get_async_redis
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.trade import CeleryTradeSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import TradeSchema
from app.schemas.trade import TradeUpdateValuesSchema
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


async def execute_celery_buy_trade_task(trade_payload_json, config_file):
    payload_schema = CeleryTradeSchema(**json.loads(trade_payload_json))
    async_redis = await get_async_redis(config_file)

    option_chain = await get_option_chain(
        async_redis,
        payload_schema.symbol,
        expiry=payload_schema.expiry,
        option_type=payload_schema.option_type,
    )

    strike, entry_price = get_strike_and_entry_price(
        option_chain,
        strike=payload_schema.strike,
        premium=payload_schema.premium,
        future_price=payload_schema.future_entry_price_received,
    )

    future_entry_price = await get_future_price(
        async_redis, payload_schema.symbol, payload_schema.expiry
    )

    # TODO: please remove this when we focus on explicitly buying only futures because strike is Null for futures
    if not strike:
        return None

    if broker_id := payload_schema.broker_id:
        print("broker_id", broker_id)
        # TODO: fix this for alice blue
        # status, entry_price = buy_alice_blue_trades(
        #     data,
        #     expiry,
        #     NFO_TYPE.OPTION,
        # )

        # if status == STATUS.COMPLETE:
        #     data["entry_price"] = entry_price
        # else:
        #     # Order not successful so dont place it in db
        #     return None

    # if we already have a strike in the payload then remove it
    # as we have successfully fetched the available strike from option_chain

    del payload_schema.strike
    del payload_schema.premium
    del payload_schema.broker_id

    async with db():
        # Use the AsyncSession to perform database operations
        # Example: Create a new entry in the database
        trade_schema = TradeSchema(
            strike=strike,
            entry_price=entry_price,
            future_entry_price=future_entry_price,
            **payload_schema.dict(),
        )

        trade_model = TradeModel(**trade_schema.dict(exclude={"premium", "broker_id", "symbol"}))
        db.session.add(trade_model)
        await db.session.flush()
        await db.session.refresh(trade_model)
        # Add trade to redis, which was earlier taken care by @event.listens_for(TradeModel, "after_insert")
        # it works i confirmed this with python_console with dummy data,
        # interesting part is to get such trades i have to call lrange with 0, -1
        async_redis = await get_async_redis(config_file)
        trade_key = f"{trade_model.strategy_id} {trade_model.expiry} {trade_model.option_type}"
        trade = RedisTradeSchema.from_orm(trade_model).json()
        await async_redis.rpush(trade_key, trade)

    return "successfully added trade to db"


async def execute_celery_exit_trade_task(
    payload_json, redis_ongoing_key, exiting_trades_json, config_file
):
    celery_trade_schema = CeleryTradeSchema(**json.loads(payload_json))
    exiting_trades = [json.loads(trade) for trade in json.loads(exiting_trades_json)]
    async_redis = await get_async_redis(config_file)

    strike_exit_price_dict = await get_strike_and_exit_price_dict(
        async_redis, celery_trade_schema, exiting_trades
    )

    future_exit_price = await get_future_price(
        async_redis, celery_trade_schema.symbol, celery_trade_schema.expiry
    )

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
            # received_exit_at is basically the signal received at
            "received_at": celery_trade_schema.entry_received_at,
        }
        close_trade_schema = TradeUpdateValuesSchema(**mapping)
        updated_values.append(close_trade_schema)
        total_profit += close_trade_schema.profit
        total_future_profit += close_trade_schema.future_profit

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
                },
            )

        await db.session.flush()
        await async_redis.delete(redis_ongoing_key)
    logging.info(
        "successfully closed trades and updated the take_away_profit table with the profit and deleted the redis key"
    )
    return "successfully closed trades and updated the take_away_profit table with the profit and deleted the redis key"
