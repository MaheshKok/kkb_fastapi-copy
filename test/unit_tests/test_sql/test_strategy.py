import pytest
from sqlalchemy import select

from app.database.models import Strategy
from test.factory.strategy import StrategyFactory
from test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_strategy_sql(async_session):
    user = await UserFactory(async_session=async_session)
    for _ in range(10):
        await StrategyFactory(async_session=async_session, user=user)

    result = await async_session.execute(select(Strategy))
    assert len(result.all()) == 10
