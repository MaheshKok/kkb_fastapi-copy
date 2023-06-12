from datetime import datetime

import pytest
from sqlalchemy import Select
from tasks.tasks import task_buying_trade

from app.api.utils import get_current_and_next_expiry
from app.database.models import TradeModel
from app.database.models.strategy import StrategyModel
from app.utils.constants import ConfigFile
from test.conftest import create_closed_trades
from test.unit_tests.test_data import get_test_post_trade_payload


@pytest.mark.asyncio
@pytest.mark.parametrize("option_type", ["CE", "PE"], ids=["CE Options", "PE Options"])
async def test_buy_trade_for_premium_and_add_trades_to_new_key_in_redis(
    async_session,
    option_type,
    patch_redis_add_trades_to_new_key,
):
    test_trade_data = get_test_post_trade_payload()
    if option_type == "PE":
        test_trade_data["option_type"] = "PE"

    await create_closed_trades(async_session, users=1, strategies=1, trades=0)
    # query database for stragey

    fetch_strategy_query_ = await async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()

    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        datetime.now().date()
    )

    test_trade_data["strategy_id"] = strategy_model.id
    test_trade_data["symbol"] = strategy_model.symbol
    test_trade_data["expiry"] = current_expiry_date

    await task_buying_trade(test_trade_data, ConfigFile.TEST)

    await async_session.flush()
    fetch_trades_query_ = await async_session.execute(Select(TradeModel))
    trades = fetch_trades_query_.scalars().all()
    assert len(trades) == 1
    trade_model = trades[0]
    assert trade_model.strategy.id == strategy_model.id
    assert trade_model.entry_price <= test_trade_data["premium"]

    # trades are being added to redis
    assert patch_redis_add_trades_to_new_key.exists.called
    assert patch_redis_add_trades_to_new_key.lpush.called


@pytest.mark.asyncio
@pytest.mark.parametrize("option_type", ["CE", "PE"], ids=["CE Options", "PE Options"])
async def test_buy_trade_for_premium_and_add_trade_to_ongoing_trades_in_redis(
    async_session,
    option_type,
    patch_redis_add_trade_to_ongoing_trades,
):
    test_trade_data = get_test_post_trade_payload()
    if option_type == "PE":
        test_trade_data["option_type"] = "PE"

    # We dont need to create closed trades here explicitly
    # because patch_redis_add_trade_to_ongoing_trades already takes care of it

    # query database for strategy
    fetch_strategy_query_ = await async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()

    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        datetime.now().date()
    )

    test_trade_data["strategy_id"] = strategy_model.id
    test_trade_data["symbol"] = strategy_model.symbol
    test_trade_data["expiry"] = current_expiry_date

    await task_buying_trade(test_trade_data, ConfigFile.TEST)

    await async_session.flush()
    # the top most trade is the one which is just created
    fetch_trades_query_ = await async_session.execute(
        Select(TradeModel).order_by(TradeModel.entry_at.desc())
    )
    trades = fetch_trades_query_.scalars().all()
    assert len(trades) == 11
    trade_model = trades[0]
    assert trade_model.strategy.id == strategy_model.id
    assert trade_model.entry_price <= test_trade_data["premium"]

    # trades are being added to redis
    assert patch_redis_add_trade_to_ongoing_trades.exists.called
    assert patch_redis_add_trade_to_ongoing_trades.lrange.called
    assert patch_redis_add_trade_to_ongoing_trades.lpush.called


@pytest.mark.parametrize(
    "payload_strike", ["43500.0", "43510.0"], ids=["valid strike", "invalid strike"]
)
@pytest.mark.asyncio
async def test_buy_trade_for_strike(
    async_session,
    payload_strike,
    patch_redis_add_trade_to_ongoing_trades,
):
    test_trade_data = get_test_post_trade_payload()
    del test_trade_data["premium"]
    test_trade_data["strike"] = payload_strike

    # We dont need to create closed trades here explicitly
    # because patch_redis_add_trade_to_ongoing_trades already takes care of it

    # query database for stragey

    fetch_strategy_query_ = await async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()

    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        datetime.now().date()
    )

    test_trade_data["strategy_id"] = strategy_model.id
    test_trade_data["symbol"] = strategy_model.symbol
    test_trade_data["expiry"] = current_expiry_date

    await task_buying_trade(test_trade_data, ConfigFile.TEST)

    await async_session.flush()
    # the top most trade is the one which is just created
    fetch_trades_query_ = await async_session.execute(
        Select(TradeModel).order_by(TradeModel.entry_at.desc())
    )
    trades = fetch_trades_query_.scalars().all()
    assert len(trades) == 11
    trade_model = trades[0]
    assert trade_model.strategy.id == strategy_model.id
    assert trade_model.strike <= float(payload_strike)
