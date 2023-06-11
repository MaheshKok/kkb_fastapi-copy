import pytest
from sqlalchemy import select

from app.database.models import TradeModel
from test.factory.strategy import StrategyFactory
from test.factory.trade import TradeFactory
from test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_trade_factory(async_session):
    user = await UserFactory(async_session=async_session)
    strategy = await StrategyFactory(async_session=async_session, user=user)

    for _ in range(10):
        _ = await TradeFactory(async_session=async_session, strategy=strategy)

    result = await async_session.execute(select(TradeModel))
    assert len(result.all()) == 10


@pytest.mark.asyncio
async def test_trade_factory_with_invalid_position(async_session):
    user = await UserFactory(async_session=async_session)
    strategy = await StrategyFactory(async_session=async_session, user=user)

    for _ in range(10):
        _ = await TradeFactory(async_session=async_session, strategy=strategy, position="INVALID")

    result = await async_session.execute(select(TradeModel))
    assert len(result.all()) == 10
