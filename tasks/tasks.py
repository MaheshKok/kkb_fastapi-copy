from datetime import datetime

from sqlalchemy import bindparam
from sqlalchemy import select
from sqlalchemy import update
from tasks.utils import _get_async_session_maker
from tasks.utils import get_future_price
from tasks.utils import get_strike_and_entry_price
from tasks.utils import get_strike_and_exit_price_dict

from app.database.models import TakeAwayProfit
from app.database.models import TradeModel
from app.extensions.celery_tasks import celery
from app.extensions.redis_cache import redis
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.trade import CloseTradeSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import TradeSchema
from app.utils.option_chain import get_option_chain


def get_profit(entry_price, exit_price, quantity, position):
    if position == PositionEnum.LONG:
        profit = (exit_price - entry_price) * quantity
    else:
        profit = (exit_price - entry_price) * quantity

    return profit


@celery.task(name="tasks.closing_trade")
async def task_closing_trade(trade_payload, redis_ongoing_key, redis_ongoing_trades, config_file):
    strike_exit_price_dict = await get_strike_and_exit_price_dict(
        trade_payload, redis_ongoing_trades
    )
    received_at = trade_payload["received_at"]
    future_exit_price = await get_future_price(trade_payload["symbol"], trade_payload["expiry"])

    async_session_maker = _get_async_session_maker(config_file)

    updated_values = []
    total_profit = 0
    total_future_profit = 0
    async with async_session_maker as async_session:
        for trade in redis_ongoing_trades:
            entry_price = trade["entry_price"]
            quantity = trade["quantity"]
            position = trade["position"]
            exit_price = strike_exit_price_dict[trade["strike"]]
            profit = get_profit(entry_price, exit_price, quantity, position)

            future_entry_price = trade["future_entry_price"]
            # if option_type is PE then position is SHORT and for CE its LONG
            future_position = (
                PositionEnum.SHORT
                if trade["option_type"] == OptionTypeEnum.PE
                else PositionEnum.LONG
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
                # received_exit_at is basically received_at
                "received_at": received_at,
            }
            close_trade_schema = CloseTradeSchema(**mapping)
            updated_values.append(close_trade_schema)
            total_profit += close_trade_schema.profit
            total_future_profit += close_trade_schema.future_profit

        fetch_take_away_profit_query_ = await async_session.execute(
            select(TakeAwayProfit).filter_by(strategy_id=trade["strategy_id"])
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()

        if take_away_profit_model:
            take_away_profit_model.profit += total_profit
            take_away_profit_model.future_profit += total_future_profit
            take_away_profit_model.total_trades += len(redis_ongoing_trades)
            take_away_profit_model.updated_at = datetime.now()
            await async_session.commit()
        else:
            take_away_profit_model = TakeAwayProfit(
                profit=total_profit,
                future_profit=total_future_profit,
                strategy_id=trade["strategy_id"],
                total_trades=len(redis_ongoing_trades),
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

        await async_session.flush()
        await redis.delete(redis_ongoing_key)
        return "successfully closed trades and updated the take_away_profit table with the profit and deleted the redis key"


@celery.task(name="tasks.buying_trade")
async def task_buying_trade(trade_payload, config_file):
    option_chain = await get_option_chain(
        trade_payload["symbol"],
        expiry=trade_payload["expiry"],
        option_type=trade_payload["option_type"],
    )

    strike, entry_price = get_strike_and_entry_price(
        option_chain,
        strike=trade_payload.get("strike"),
        premium=trade_payload.get("premium"),
        future_price=trade_payload.get("future_entry_price_received"),
    )
    future_entry_price = await get_future_price(trade_payload["symbol"], trade_payload["expiry"])

    # TODO: please remove this when we focus on explicitly buying only futures because strike is Null for futures
    if not strike:
        return None

    # if we already have a strike in the payload then remove it
    # as we have successfully fetched the available strike from option_chain
    if "strike" in trade_payload:
        trade_payload.pop("strike")

    if broker_id := trade_payload.get("broker_id"):
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

    async_session_maker = _get_async_session_maker(config_file)

    async with async_session_maker as async_session:
        # Use the AsyncSession to perform database operations
        # Example: Create a new entry in the database
        trade_schema = TradeSchema(
            strike=strike,
            entry_price=entry_price,
            future_entry_price=future_entry_price,
            **trade_payload,
        )
        trade_model = TradeModel(**trade_schema.dict(exclude={"premium"}))
        async_session.add(trade_model)
        await async_session.commit()
        await async_session.refresh(trade_model)

        # Add trade to redis, which was earlier taken care by @event.listens_for(TradeModel, "after_insert")
        # it works i confirmed this with python_console with dummy data,
        # interesting part is to get such trades i have to call lrange with 0, -1
        trade_key = f"{trade_model.strategy_id} {trade_model.expiry} {trade_model.option_type}"
        trade = RedisTradeSchema.from_orm(trade_model).json()
        if not await redis.exists(trade_key):
            await redis.lpush(trade_key, trade)
        else:
            current_trades = await redis.lrange(trade_key, 0, -1)
            updated_trades = current_trades + [trade]
            await redis.delete(trade_key)
            await redis.lpush(trade_key, *updated_trades)

        return "successfully added trade to db"
