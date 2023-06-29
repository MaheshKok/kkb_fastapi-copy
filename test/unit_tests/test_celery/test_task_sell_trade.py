import pytest
from fastapi_sa.database import db
from sqlalchemy import select
from tasks.execution import task_exit_trade

from app.database.models import TakeAwayProfit
from app.database.models import TradeModel
from test.unit_tests.test_celery.conftest import celery_sell_task_args


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("take_away_profit", "ce_trade"),
    [
        (False, True),
        (False, False),
    ],
    ids=[
        "sell_ce_trade_without_take_away_profit",
        "sell_pe_trade_without_take_away_profit",
    ],
)
async def test_celery_sell_trade_without_take_away_profit(
    test_async_redis_client, take_away_profit, ce_trade
):
    async with db():
        (
            strategy_model_id,
            signal_payload_schema,
            redis_ongoing_key,
            redis_trades_json,
        ) = await celery_sell_task_args(
            test_async_redis_client, take_away_profit=take_away_profit, ce_trade=ce_trade
        )

        # assert we dont have takeawayprofit model before closing trades
        fetch_take_away_profit_query_ = await db.session.execute(
            select(TakeAwayProfit).filter_by(strategy_id=strategy_model_id)
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
        assert take_away_profit_model is None

        assert await test_async_redis_client.exists(redis_ongoing_key)

        await task_exit_trade(
            signal_payload_schema, redis_ongoing_key, redis_trades_json, test_async_redis_client
        )

        fetch_trades_query_ = await db.session.execute(select(TradeModel))
        trades = fetch_trades_query_.scalars().all()

        # Refresh each trade individually
        for trade in trades:
            await db.session.refresh(trade)

        assert len(trades) == 10

        profit_to_be_added = sum(trade.profit for trade in trades)

        fetch_take_away_profit_query_ = await db.session.execute(
            select(TakeAwayProfit).filter_by(strategy_id=strategy_model_id)
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
        await db.session.refresh(take_away_profit_model)
        assert take_away_profit_model.profit == profit_to_be_added

        # key has been removed from redis
        assert not await test_async_redis_client.exists(redis_ongoing_key)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("take_away_profit", "ce_trade"),
    [
        (True, True),
        (True, False),
    ],
    ids=[
        "sell_ce_trade_updating_take_away_profit",
        "sell_pe_trade_updating_take_away_profit",
    ],
)
async def test_celery_sell_trade_updating_takeaway_profit(
    test_async_redis_client, take_away_profit, ce_trade
):
    async with db():
        (
            strategy_model_id,
            signal_payload_schema,
            redis_ongoing_key,
            redis_trades_json,
        ) = await celery_sell_task_args(
            test_async_redis_client, take_away_profit=True, ce_trade=False
        )

        # assert we dont have takeawayprofit model before closing trades
        fetch_take_away_profit_query_ = await db.session.execute(
            select(TakeAwayProfit).filter_by(strategy_id=strategy_model_id)
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
        assert take_away_profit_model is not None
        earlier_take_away_profit = take_away_profit_model.profit

        assert await test_async_redis_client.exists(redis_ongoing_key)

        await task_exit_trade(
            signal_payload_schema, redis_ongoing_key, redis_trades_json, test_async_redis_client
        )

        fetch_trades_query_ = await db.session.execute(select(TradeModel))
        trades = fetch_trades_query_.scalars().all()

        # Refresh each trade individually
        for trade in trades:
            await db.session.refresh(trade)

        assert len(trades) == 10

        profit_to_be_added = sum(trade.profit for trade in trades)

        fetch_take_away_profit_query_ = await db.session.execute(
            select(TakeAwayProfit).filter_by(strategy_id=strategy_model_id)
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
        await db.session.refresh(take_away_profit_model)
        assert take_away_profit_model.profit == earlier_take_away_profit + profit_to_be_added

        # key has been removed from redis
        assert not await test_async_redis_client.exists(redis_ongoing_key)


# TODO: assert exit_at, profit, future_profit, exit_received_at < exit_at ,
# TODO: you havent yet deducted brokerage fees and govt charges which are approximately 60
# TODO: add cron jobs like update yesterdays profit
# unit test for all edge case like two days holidays consecutive
#
