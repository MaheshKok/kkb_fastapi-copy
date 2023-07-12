import httpx
import pytest
from sqlalchemy import select

from app.database.models import StrategyModel
from app.database.models import TakeAwayProfitModel
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.strategy import StrategySchema
from app.tasks.tasks import task_exit_trade
from test.unit_tests.test_async_trade_tasks.conftest import sell_task_args


# I just fixed them , but didnt assert so many things which are mentioned at the bottom


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
async def test_sell_trade_without_take_away_profit(
    test_async_redis_client, take_away_profit, ce_trade
):
    (
        strategy_model_id,
        signal_payload_schema,
        redis_ongoing_key,
        redis_trade_schema_list,
    ) = await sell_task_args(
        test_async_redis_client, take_away_profit=take_away_profit, ce_trade=ce_trade
    )

    async with Database() as async_session:
        # assert we dont have takeawayprofit model before closing trades
        fetch_take_away_profit_query_ = await async_session.execute(
            select(TakeAwayProfitModel).filter_by(strategy_id=strategy_model_id)
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
        assert take_away_profit_model is None

        assert await test_async_redis_client.exists(redis_ongoing_key)
        strategy_model = await async_session.get(StrategyModel, strategy_model_id)
        strategy_schema = StrategySchema.from_orm(strategy_model)

        await task_exit_trade(
            signal_payload_schema=signal_payload_schema,
            redis_ongoing_key=redis_ongoing_key,
            redis_trade_schema_list=redis_trade_schema_list,
            async_redis_client=test_async_redis_client,
            strategy_schema=strategy_schema,
            async_httpx_client=httpx.AsyncClient(),
        )

        fetch_trades_query_ = await async_session.execute(select(TradeModel))
        trades = fetch_trades_query_.scalars().all()

        # Refresh each trade individually
        for trade in trades:
            await async_session.refresh(trade)

        assert len(trades) == 10

        profit_to_be_added = round(sum(trade.profit for trade in trades), 2)

        fetch_take_away_profit_query_ = await async_session.execute(
            select(TakeAwayProfitModel).filter_by(strategy_id=strategy_model_id)
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
        await async_session.refresh(take_away_profit_model)
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
async def test_sell_trade_updating_takeaway_profit(
    test_async_redis_client, take_away_profit, ce_trade
):
    (
        strategy_model_id,
        signal_payload_schema,
        redis_ongoing_key,
        redis_trade_schema_list,
    ) = await sell_task_args(test_async_redis_client, take_away_profit=True, ce_trade=False)

    async with Database() as async_session:
        # assert we dont have takeawayprofit model before closing trades
        fetch_take_away_profit_query_ = await async_session.execute(
            select(TakeAwayProfitModel).filter_by(strategy_id=strategy_model_id)
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
        assert take_away_profit_model is not None
        earlier_take_away_profit = take_away_profit_model.profit

        assert await test_async_redis_client.exists(redis_ongoing_key)

        strategy_model = await async_session.get(StrategyModel, strategy_model_id)
        strategy_schema = StrategySchema.from_orm(strategy_model)

        await task_exit_trade(
            signal_payload_schema=signal_payload_schema,
            redis_ongoing_key=redis_ongoing_key,
            redis_trade_schema_list=redis_trade_schema_list,
            async_redis_client=test_async_redis_client,
            strategy_schema=strategy_schema,
            async_httpx_client=httpx.AsyncClient(),
        )

        fetch_trades_query_ = await async_session.execute(select(TradeModel))
        trades = fetch_trades_query_.scalars().all()

        # Refresh each trade individually
        for trade in trades:
            await async_session.refresh(trade)

        assert len(trades) == 10

        profit_to_be_added = round(sum(trade.profit for trade in trades), 2)

        fetch_take_away_profit_query_ = await async_session.execute(
            select(TakeAwayProfitModel).filter_by(strategy_id=strategy_model_id)
        )
        take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
        await async_session.refresh(take_away_profit_model)
        assert take_away_profit_model.profit == earlier_take_away_profit + profit_to_be_added

        # key has been removed from redis
        assert not await test_async_redis_client.exists(redis_ongoing_key)


# TODO: assert exit_at, profit, future_profit, exit_received_at < exit_at ,
# TODO: add cron jobs like update yesterdays profit
# unit test for all edge case like two days holidays consecutive
#
