import pytest
from sqlalchemy import select

from app.database.models import TradeModel
from test.factory.strategy import StrategyFactory
from test.factory.trade import CompletedTradeFactory
from test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_trade_factory(test_async_session):
    user = await UserFactory(async_session=test_async_session)
    strategy = await StrategyFactory(async_session=test_async_session, user=user)

    for _ in range(10):
        _ = await CompletedTradeFactory(async_session=test_async_session, strategy=strategy)

    result = await test_async_session.execute(select(TradeModel))
    assert len(result.all()) == 10


@pytest.mark.asyncio
async def test_trade_factory_with_invalid_position(test_async_session):
    user = await UserFactory(async_session=test_async_session)
    strategy = await StrategyFactory(async_session=test_async_session, user=user)

    for _ in range(10):
        _ = await CompletedTradeFactory(
            async_session=test_async_session, strategy=strategy, position="INVALID"
        )

    result = await test_async_session.execute(select(TradeModel))
    assert len(result.all()) == 10
