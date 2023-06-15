import pytest
from sqlalchemy import Select
from tasks.tasks import task_buying_trade

from app.database.models import TradeModel
from app.database.models.strategy import StrategyModel
from app.utils.constants import ConfigFile


@pytest.mark.asyncio
@pytest.mark.parametrize("option_type", ["CE", "PE"], ids=["CE Options", "PE Options"])
async def test_buy_trade_for_premium_and_add_trades_to_new_key_in_redis(
    test_async_session,
    option_type,
    get_task_trade_payload,
):
    test_trade_data = get_task_trade_payload

    if option_type == "PE":
        test_trade_data["option_type"] = "PE"

    fetch_strategy_query_ = await test_async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()

    await task_buying_trade(test_trade_data, ConfigFile.TEST)

    await test_async_session.flush()
    fetch_trades_query_ = await test_async_session.execute(
        Select(TradeModel).order_by(TradeModel.entry_at.desc())
    )
    trades = fetch_trades_query_.scalars().all()
    assert len(trades) == 11
    trade_model = trades[0]
    assert trade_model.strategy.id == strategy_model.id
    assert trade_model.entry_price <= test_trade_data["premium"]


@pytest.mark.asyncio
@pytest.mark.parametrize("option_type", ["CE", "PE"], ids=["CE Options", "PE Options"])
async def test_buy_trade_for_premium_and_add_trade_to_ongoing_trades_in_redis(
    test_async_session, test_async_redis, option_type, get_task_trade_payload
):
    test_trade_data = get_task_trade_payload
    if option_type == "PE":
        test_trade_data["option_type"] = "PE"

    # We dont need to create closed trades here explicitly
    # because get_task_trade_payload already takes care of it

    # query database for strategy
    fetch_strategy_query_ = await test_async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()

    await task_buying_trade(test_trade_data, ConfigFile.TEST)

    await test_async_session.flush()
    # the top most trade is the one which is just created
    fetch_trades_query_ = await test_async_session.execute(
        Select(TradeModel).order_by(TradeModel.entry_at.desc())
    )
    trades = fetch_trades_query_.scalars().all()
    assert len(trades) == 11
    trade_model = trades[0]
    assert trade_model.strategy.id == strategy_model.id
    assert trade_model.entry_price <= test_trade_data["premium"]

    # trades are being added to redis


@pytest.mark.parametrize(
    "payload_strike", ["43500.0", "43510.0"], ids=["valid strike", "invalid strike"]
)
@pytest.mark.asyncio
async def test_buy_trade_for_strike(
    test_async_session, payload_strike, test_async_redis, get_task_trade_payload
):
    test_trade_data = get_task_trade_payload
    del test_trade_data["premium"]
    test_trade_data["strike"] = payload_strike

    # We dont need to create closed trades here explicitly
    # because get_task_trade_payload already takes care of it

    # query database for stragey
    fetch_strategy_query_ = await test_async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()

    await task_buying_trade(test_trade_data, ConfigFile.TEST)

    await test_async_session.flush()
    # the top most trade is the one which is just created
    fetch_trades_query_ = await test_async_session.execute(
        Select(TradeModel).order_by(TradeModel.entry_at.desc())
    )
    trades = fetch_trades_query_.scalars().all()
    assert len(trades) == 11
    trade_model = trades[0]
    assert trade_model.strategy.id == strategy_model.id
    assert trade_model.strike <= float(payload_strike)
