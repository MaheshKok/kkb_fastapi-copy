import asyncio
import json
import ssl
from datetime import datetime

from celery import Celery
from sqlalchemy import bindparam
from sqlalchemy import select
from sqlalchemy import update
from tasks.utils import _get_async_session_maker
from tasks.utils import get_async_redis
from tasks.utils import get_future_price
from tasks.utils import get_strike_and_entry_price
from tasks.utils import get_strike_and_exit_price_dict

from app.core.config import get_config
from app.database.models import TakeAwayProfit
from app.database.models import TradeModel
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.trade import CeleryTradeSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import TradeSchema
from app.schemas.trade import TradeUpdateValuesSchema
from app.utils.option_chain import get_option_chain


config = get_config()
redis_url = config.data["celery_redis"]["url"]

celery = Celery(
    "KokoBrothersBackend",
    broker=redis_url,
    backend=redis_url,
    broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    include=["tasks.tasks"],
    broker_connection_retry_on_startup=True,
)


def get_profit(entry_price, exit_price, quantity, position):
    if position == PositionEnum.LONG:
        profit = (exit_price - entry_price) * quantity
    else:
        profit = (exit_price - entry_price) * quantity

    return profit


@celery.task(name="tasks.exiting_trades")
def task_exiting_trades(payload_json, redis_ongoing_key, exiting_trades_json, config_file):
    # Create a new event loop
    loop = asyncio.new_event_loop()

    # Set the event loop as the default for the current context
    asyncio.set_event_loop(loop)

    # Use the event loop to run the asynchronous function
    result = loop.run_until_complete(
        execute_celery_exit_async_task(
            payload_json, redis_ongoing_key, exiting_trades_json, config_file
        )
    )

    # Return the result
    return result


async def execute_celery_exit_async_task(
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

    async_session_maker = _get_async_session_maker(config_file)

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

    async with async_session_maker as async_session:
        fetch_take_away_profit_query_ = await async_session.execute(
            select(TakeAwayProfit).filter_by(strategy_id=trade["strategy_id"])
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()

        if take_away_profit_model:
            take_away_profit_model.profit += total_profit
            take_away_profit_model.future_profit += total_future_profit
            take_away_profit_model.total_trades += len(exiting_trades)
            take_away_profit_model.updated_at = datetime.now()
            await async_session.commit()
        else:
            take_away_profit_model = TakeAwayProfit(
                profit=total_profit,
                future_profit=total_future_profit,
                strategy_id=trade["strategy_id"],
                total_trades=len(exiting_trades),
            )
            async_session.add(take_away_profit_model)
            await async_session.flush()

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
            await async_session.execute(
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

        await async_session.commit()
        await async_redis.delete(redis_ongoing_key)
    return "successfully closed trades and updated the take_away_profit table with the profit and deleted the redis key"


@celery.task(name="tasks.buying_trade")
def task_buying_trade(payload_json, config_file):
    # Create a new event loop
    loop = asyncio.new_event_loop()

    # Set the event loop as the default for the current context
    asyncio.set_event_loop(loop)

    # Use the event loop to run the asynchronous function
    result = loop.run_until_complete(execute_celery_buy_async_task(payload_json, config_file))

    # Return the result
    return result


async def execute_celery_buy_async_task(trade_payload_json, config_file):
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

    async_session_maker = _get_async_session_maker(config_file)

    async with async_session_maker as async_session:
        # Use the AsyncSession to perform database operations
        # Example: Create a new entry in the database
        trade_schema = TradeSchema(
            strike=strike,
            entry_price=entry_price,
            future_entry_price=future_entry_price,
            **payload_schema.dict(),
        )

        trade_model = TradeModel(**trade_schema.dict(exclude={"premium", "broker_id"}))
        async_session.add(trade_model)
        await async_session.commit()
        await async_session.refresh(trade_model)

        # Add trade to redis, which was earlier taken care by @event.listens_for(TradeModel, "after_insert")
        # it works i confirmed this with python_console with dummy data,
        # interesting part is to get such trades i have to call lrange with 0, -1
        async_redis = await get_async_redis(config_file)
        trade_key = f"{trade_model.strategy_id} {trade_model.expiry} {trade_model.option_type}"
        trade = RedisTradeSchema.from_orm(trade_model).json()
        if not await async_redis.exists(trade_key):
            await async_redis.lpush(trade_key, trade)
        else:
            current_trades = await async_redis.lrange(trade_key, 0, -1)
            updated_trades = current_trades + [trade]
            await async_redis.delete(trade_key)
            await async_redis.lpush(trade_key, *updated_trades)

    return "successfully added trade to db"
