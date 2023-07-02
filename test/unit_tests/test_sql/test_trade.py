import pytest
from sqlalchemy import select

from app.database.models import TradeModel
from app.database.sqlalchemy_client.client import Database
from test.factory.strategy import StrategyFactory
from test.factory.trade import CompletedTradeFactory
from test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_trade_factory():
    user = await UserFactory()
    strategy = await StrategyFactory(user=user)

    for _ in range(10):
        _ = await CompletedTradeFactory(strategy=strategy)

    async with Database() as async_session:
        result = await async_session.scalars(select(TradeModel))
        assert len(result.all()) == 10


@pytest.mark.asyncio
async def test_trade_factory_with_invalid_position():
    user = await UserFactory()
    strategy = await StrategyFactory(user=user)

    for _ in range(10):
        _ = await CompletedTradeFactory(strategy=strategy, position="INVALID")

    async with Database() as async_session:
        result = await async_session.scalars(select(TradeModel))
        assert len(result.all()) == 10
