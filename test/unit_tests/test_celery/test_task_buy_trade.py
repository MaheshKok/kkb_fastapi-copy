from datetime import datetime

import pytest
from sqlalchemy import Select
from tasks.tasks import task_buying_trade

from app.api.utils import get_current_and_next_expiry
from app.database.models import TradeModel
from app.database.models.strategy import StrategyModel
from app.utils.constants import ConfigFile
from test.conftest import create_ecosystem
from test.unit_tests.test_data import get_test_post_trade_payload


@pytest.mark.asyncio
@pytest.mark.parametrize("option_type", ["CE", "PE"], ids=["CE Options", "PE Options"])
async def test_buy_trade_for_premium(async_session, option_type, patch_redis_option_chain):
    test_trade_data = get_test_post_trade_payload()
    if option_type == "PE":
        test_trade_data["option_type"] = "PE"

    await create_ecosystem(async_session, users=1, strategies=1, trades=0)
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


@pytest.mark.parametrize(
    "payload_strike", ["43500.0", "43510.0"], ids=["valid strike", "invalid strike"]
)
@pytest.mark.asyncio
async def test_buy_trade_for_strike(async_session, patch_redis_option_chain, payload_strike):
    test_trade_data = get_test_post_trade_payload()
    del test_trade_data["premium"]
    test_trade_data["strike"] = payload_strike

    await create_ecosystem(async_session, users=1, strategies=1, trades=0)
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
    assert trade_model.strike <= float(payload_strike)
