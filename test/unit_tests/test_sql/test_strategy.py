import pytest
from sqlalchemy import select

from app.database.models import StrategyModel
from app.database.sqlalchemy_client.client import Database
from test.factory.strategy import StrategyFactory
from test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_strategy_factory():
    user = await UserFactory()
    for _ in range(10):
        await StrategyFactory(user=user)

    async with Database() as async_session:
        result = await async_session.scalars(select(StrategyModel))
        assert len(result.all()) == 10


@pytest.mark.asyncio
async def test_strategy_factory_with_invalid_position():
    user = await UserFactory()
    await StrategyFactory(user=user, position="INVALID")

    async with Database() as async_session:
        result = await async_session.scalars(select(StrategyModel))
        assert len(result.all()) == 1
