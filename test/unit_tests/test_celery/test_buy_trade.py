from datetime import datetime

import pytest
from sqlalchemy import Select
from tasks.tasks import task_buying_trade

from app.api.utils import get_current_and_next_expiry
from app.database.models import TradeModel
from app.database.models.strategy import Strategy
from app.utils.constants import ConfigFile
from test.conftest import create_ecosystem


@pytest.mark.asyncio
async def test_buy_trade(async_session, test_trade_data):
    await create_ecosystem(async_session, users=1, strategies=1, trades=0)
    # query database for stragey

    fetch_strategy_query_ = await async_session.execute(Select(Strategy))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()

    todays_date = datetime.now().date()
    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        todays_date
    )

    test_trade_data["strategy_id"] = strategy_model.id
    test_trade_data["symbol"] = strategy_model.symbol
    test_trade_data["expiry"] = current_expiry_date

    await task_buying_trade(test_trade_data, ConfigFile.TEST)

    await async_session.flush()
    fetch_trades_query_ = await async_session.execute(Select(TradeModel))
    trades = fetch_trades_query_.scalars().all()
    assert len(trades) == 1
    assert trades[0].strategy.id == strategy_model.id
