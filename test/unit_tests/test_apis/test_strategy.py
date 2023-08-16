from uuid import UUID

import pytest
from sqlalchemy import select

from app.database.models import StrategyModel
from app.database.session_manager.db_session import Database
from test.factory.strategy import StrategyFactory
from test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_get_empty_strategys(test_async_client):
    response = await test_async_client.get("/api/strategy")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_strategys(test_async_client):
    # create a strategy
    user = await UserFactory()
    for _ in range(10):
        await StrategyFactory(user=user)

    async with Database() as async_session:
        strategy_query = await async_session.scalars(select(StrategyModel.id, StrategyModel))
        strategy_ids = strategy_query.all()

        response = await test_async_client.get("/api/strategy")
        assert response.status_code == 200
        assert all(UUID(strategy_data["id"]) in strategy_ids for strategy_data in response.json())
