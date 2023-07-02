import logging
from datetime import datetime

from aioredis import Redis
from httpx import AsyncClient
from sqlalchemy import bindparam
from sqlalchemy import select
from sqlalchemy import update

from app.database.models import TakeAwayProfit
from app.database.models import TradeModel
from app.database.sqlalchemy_client.client import Database
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import ExitTradeSchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.schemas.trade import TradeSchema
from app.tasks.utils import get_future_price
from app.tasks.utils import get_strike_and_entry_price
from app.tasks.utils import get_strike_and_exit_price_dict
from app.utils.option_chain import get_option_chain


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def get_profit(entry_price, exit_price, quantity, position):
    if position == PositionEnum.LONG:
        profit = (exit_price - entry_price) * quantity - 60
    else:
        profit = (entry_price - exit_price) * quantity - 60

    return round(profit, 2)


async def task_entry_trade(
    *, signal_payload_schema, async_redis_client, strategy_schema, async_httpx_client
):
    option_chain = await get_option_chain(
        async_redis_client=async_redis_client,
        symbol=signal_payload_schema.symbol,
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
        symbol=signal_payload_schema.symbol,
        strategy_schema=strategy_schema,
    )

    async with Database() as async_session:
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
        async_session.add(trade_model)
        await async_session.flush()
        await async_session.refresh(trade_model)
        # Add trade to redis, which was earlier taken care by @event.listens_for(TradeModel, "after_insert")
        # it works i confirmed this with python_console with dummy data,
        # interesting part is to get such trades i have to call lrange with 0, -1
        trade_key = f"{trade_model.strategy_id} {trade_model.expiry} {trade_model.option_type}"
        redis_trade_json = RedisTradeSchema.from_orm(trade_model).json(exclude={"received_at"})
        await async_redis_client.rpush(trade_key, redis_trade_json)
        logging.info(f"{trade_model.id} added to db and redis")

    return "successfully added trade to db"


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
        symbol=signal_payload_schema.symbol,
        strategy_schema=strategy_schema,
    )

    updated_values = []
    total_profit = 0
    total_future_profit = 0

    for trade in redis_trade_schema_list:
        entry_price = trade.entry_price
        quantity = trade.quantity
        position = trade.position
        exit_price = strike_exit_price_dict.get(trade.strike, None)
        if not exit_price:
            # this is an alarm that exit price is not found for this strike nd this is more likely to happen for broker
            continue
        profit = get_profit(entry_price, exit_price, quantity, position)

        future_entry_price = trade.future_entry_price
        # if option_type is PE then position is SHORT and for CE its LONG
        future_position = (
            PositionEnum.SHORT if trade.option_type == OptionTypeEnum.PE else PositionEnum.LONG
        )
        future_profit = get_profit(
            future_entry_price, future_exit_price, quantity, future_position
        )

        mapping = {
            "id": trade.id,
            "exit_price": exit_price,
            "profit": profit,
            "future_exit_price": future_exit_price,
            "future_profit": future_profit,
            "exit_received_at": signal_payload_schema.received_at,
        }
        exit_trade_schema = ExitTradeSchema(**mapping)
        updated_values.append(exit_trade_schema)
        total_profit += exit_trade_schema.profit
        total_future_profit += exit_trade_schema.future_profit

    async with Database() as async_session:
        fetch_take_away_profit_query_ = await async_session.execute(
            select(TakeAwayProfit).filter_by(strategy_id=strategy_schema.id)
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()

        if take_away_profit_model:
            take_away_profit_model.profit += total_profit
            take_away_profit_model.future_profit += total_future_profit
            take_away_profit_model.total_trades += len(redis_trade_schema_list)
            take_away_profit_model.updated_at = datetime.now()
            await async_session.flush()
        else:
            take_away_profit_model = TakeAwayProfit(
                profit=total_profit,
                future_profit=total_future_profit,
                strategy_id=strategy_schema.id,
                total_trades=len(redis_trade_schema_list),
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
                    "exit_at": bindparam("exit_at"),
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
                    "exit_at": mapping.exit_at,
                },
            )

        await async_session.flush()
        await async_redis_client.delete(redis_ongoing_key)
    logging.info(
        f"{redis_ongoing_key} closed trades, updated the take_away_profit with the profit and deleted the redis key"
    )
    return f"{redis_ongoing_key} closed trades, updated the take_away_profit with the profit and deleted the redis key"
