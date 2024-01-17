import pytest
from sqlalchemy import select

from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.test.factory.strategy import StrategyFactory
from app.test.factory.trade import CompletedTradeFactory
from app.test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_trade_factory():
    user = await UserFactory()
    strategy = await StrategyFactory(user=user)

    for _ in range(10):
        _ = await CompletedTradeFactory(strategy=strategy)

    async with Database() as async_session:
        result = await async_session.scalars(select(TradeModel))
        assert len(result.all()) == 10
