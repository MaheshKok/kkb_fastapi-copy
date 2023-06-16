import json
from datetime import datetime

import pytest
from sqlalchemy import Select
from sqlalchemy import select
from tasks.tasks import task_closing_trade

from app.api.utils import get_current_and_next_expiry
from app.database.models import TakeAwayProfit
from app.database.models import TradeModel
from app.database.models.strategy import StrategyModel
from app.schemas.trade import RedisTradeSchema
from app.utils.constants import ConfigFile
from test.unit_tests.test_data import get_test_post_trade_payload
from test.utils import create_open_trades


@pytest.mark.asyncio
async def test_sell_ce_trade_without_take_away_profit(test_async_session, test_async_redis):
    await create_open_trades(test_async_session, users=1, strategies=1, trades=10)

    test_trade_data = get_test_post_trade_payload()

    # query database for stragey
    fetch_strategy_query_ = await test_async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()
    test_async_session.flush()

    fetch_trade_query_ = await test_async_session.execute(Select(TradeModel))
    trade_models = fetch_trade_query_.scalars().all()

    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        test_async_redis, datetime.now().date()
    )

    test_trade_data["strategy_id"] = strategy_model.id
    test_trade_data["symbol"] = strategy_model.symbol
    test_trade_data["expiry"] = current_expiry_date
    test_trade_data["option_type"] = "PE"

    redis_ongoing_trades = [
        json.loads(RedisTradeSchema.from_orm(trade).json()) for trade in trade_models
    ]
    redis_ongoing_key = f"{strategy_model.id} {current_expiry_date} CE"

    # assert we dont have takeawayprofit model before closing trades
    fetch_take_away_profit_query_ = await test_async_session.execute(
        select(TakeAwayProfit).filter_by(strategy_id=strategy_model.id)
    )
    take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
    assert take_away_profit_model is None

    await task_closing_trade(
        test_trade_data, redis_ongoing_key, redis_ongoing_trades, ConfigFile.TEST
    )

    await test_async_session.flush()
    fetch_trades_query_ = await test_async_session.execute(Select(TradeModel))
    trades = fetch_trades_query_.scalars().all()
    assert len(trades) == 10

    fetch_take_away_profit_query_ = await test_async_session.execute(
        select(TakeAwayProfit).filter_by(strategy_id=strategy_model.id)
    )
    take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
    assert take_away_profit_model is not None
    assert take_away_profit_model.strategy_id == strategy_model.id


@pytest.mark.asyncio
async def test_sell_ce_trade_updating_take_away_profit(test_async_session, test_async_redis):
    await create_open_trades(
        test_async_session, users=1, strategies=1, trades=10, take_away_profit=True
    )

    test_trade_data = get_test_post_trade_payload()

    # query database for stragey
    fetch_strategy_query_ = await test_async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()
    test_async_session.flush()

    fetch_trade_query_ = await test_async_session.execute(Select(TradeModel))
    trade_models = fetch_trade_query_.scalars().all()

    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        test_async_redis, datetime.now().date()
    )

    test_trade_data["strategy_id"] = strategy_model.id
    test_trade_data["symbol"] = strategy_model.symbol
    test_trade_data["expiry"] = current_expiry_date
    test_trade_data["option_type"] = "PE"

    redis_ongoing_trades = [
        json.loads(RedisTradeSchema.from_orm(trade).json()) for trade in trade_models
    ]
    redis_ongoing_key = f"{strategy_model.id} {current_expiry_date} CE"

    # assert we dont have takeawayprofit model before closing trades
    fetch_take_away_profit_query_ = await test_async_session.execute(
        select(TakeAwayProfit).filter_by(strategy_id=strategy_model.id)
    )
    take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
    assert take_away_profit_model is not None
    earlier_take_away_profit = take_away_profit_model.profit

    await task_closing_trade(
        test_trade_data, redis_ongoing_key, redis_ongoing_trades, ConfigFile.TEST
    )

    fetch_trades_query_ = await test_async_session.execute(Select(TradeModel))
    trades = fetch_trades_query_.scalars().all()

    # Refresh each trade individually
    for trade in trades:
        await test_async_session.refresh(trade)

    assert len(trades) == 10

    profit_to_be_added = sum(trade.profit for trade in trades)

    fetch_take_away_profit_query_ = await test_async_session.execute(
        select(TakeAwayProfit).filter_by(strategy_id=strategy_model.id)
    )
    take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
    await test_async_session.refresh(take_away_profit_model)
    assert take_away_profit_model.profit == earlier_take_away_profit + profit_to_be_added


@pytest.mark.asyncio
async def test_sell_pe_trade_without_take_away_profit(test_async_redis, test_async_session):
    await create_open_trades(test_async_session, users=1, strategies=1, trades=10, ce_trade=False)

    test_trade_data = get_test_post_trade_payload()

    # query database for stragey
    fetch_strategy_query_ = await test_async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()
    test_async_session.flush()

    fetch_trade_query_ = await test_async_session.execute(Select(TradeModel))
    trade_models = fetch_trade_query_.scalars().all()

    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        test_async_redis, datetime.now().date()
    )

    test_trade_data["strategy_id"] = strategy_model.id
    test_trade_data["symbol"] = strategy_model.symbol
    test_trade_data["expiry"] = current_expiry_date

    redis_ongoing_trades = [
        json.loads(RedisTradeSchema.from_orm(trade).json()) for trade in trade_models
    ]
    redis_ongoing_key = f"{strategy_model.id} {current_expiry_date} CE"

    # assert we dont have takeawayprofit model before closing trades
    fetch_take_away_profit_query_ = await test_async_session.execute(
        select(TakeAwayProfit).filter_by(strategy_id=strategy_model.id)
    )
    take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
    assert take_away_profit_model is None

    await task_closing_trade(
        test_trade_data, redis_ongoing_key, redis_ongoing_trades, ConfigFile.TEST
    )

    await test_async_session.flush()
    fetch_trades_query_ = await test_async_session.execute(Select(TradeModel))
    trades = fetch_trades_query_.scalars().all()
    assert len(trades) == 10

    fetch_take_away_profit_query_ = await test_async_session.execute(
        select(TakeAwayProfit).filter_by(strategy_id=strategy_model.id)
    )
    take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
    await test_async_session.refresh(take_away_profit_model)
    assert take_away_profit_model is not None
    assert take_away_profit_model.strategy_id == strategy_model.id


@pytest.mark.asyncio
async def test_sell_pe_trade_updating_take_away_profit(test_async_session, test_async_redis):
    await create_open_trades(
        test_async_session,
        users=1,
        strategies=1,
        trades=10,
        take_away_profit=True,
        ce_trade=False,
    )

    test_trade_data = get_test_post_trade_payload()

    # query database for stragey
    fetch_strategy_query_ = await test_async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()
    test_async_session.flush()

    fetch_trade_query_ = await test_async_session.execute(Select(TradeModel))
    trade_models = fetch_trade_query_.scalars().all()

    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        test_async_redis, datetime.now().date()
    )

    test_trade_data["strategy_id"] = str(strategy_model.id)
    test_trade_data["symbol"] = strategy_model.symbol
    test_trade_data["expiry"] = str(current_expiry_date)

    redis_ongoing_trades = [
        json.loads(RedisTradeSchema.from_orm(trade).json()) for trade in trade_models
    ]
    redis_ongoing_key = f"{strategy_model.id} {current_expiry_date} CE"

    # assert we dont have takeawayprofit model before closing trades
    fetch_take_away_profit_query_ = await test_async_session.execute(
        select(TakeAwayProfit).filter_by(strategy_id=strategy_model.id)
    )
    take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
    assert take_away_profit_model is not None

    # test_trade_data_json = json.dumps(test_trade_data)
    await task_closing_trade(
        test_trade_data, redis_ongoing_key, redis_ongoing_trades, ConfigFile.TEST
    )

    await test_async_session.flush()
    fetch_trades_query_ = await test_async_session.execute(Select(TradeModel))
    trades = fetch_trades_query_.scalars().all()
    assert len(trades) == 10

    fetch_take_away_profit_query_ = await test_async_session.execute(
        select(TakeAwayProfit).filter_by(strategy_id=strategy_model.id)
    )
    take_away_profit_model = fetch_take_away_profit_query_.scalars().one_or_none()
    await test_async_session.refresh(take_away_profit_model)
    assert take_away_profit_model is not None
    assert take_away_profit_model.strategy_id == strategy_model.id
