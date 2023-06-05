from test.factory.strategy import StrategyFactory
from test.factory.user import UserFactory

import pytest


@pytest.mark.asyncio
async def test_strategy_sql(async_session):
    user = await UserFactory(async_session=async_session)
    strategy = await StrategyFactory(async_session=async_session, user=user)
    assert strategy.id is not None
