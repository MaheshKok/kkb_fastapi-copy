import pytest
from sqlalchemy import select

from app.database.models import StrategyModel
from test.factory.strategy import StrategyFactory
from test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_strategy_factory(test_async_session):
    user = await UserFactory(async_session=test_async_session)
    for _ in range(10):
        await StrategyFactory(async_session=test_async_session, user=user)

    result = await test_async_session.execute(select(StrategyModel))
    assert len(result.all()) == 10


@pytest.mark.asyncio
async def test_strategy_factory_with_invalid_position(test_async_session):
    user = await UserFactory(async_session=test_async_session)
    await StrategyFactory(async_session=test_async_session, user=user, position="INVALID")

    result = await test_async_session.execute(select(StrategyModel))
    assert len(result.all()) == 1
