from uuid import UUID

import pytest
from sqlalchemy import select

from app.database.models import TakeAwayProfitModel
from app.database.session_manager.db_session import Database
from app.test.utils import create_open_trades


@pytest.mark.asyncio
async def test_get_empty_takeaway_profit(test_async_client):
    response = await test_async_client.get("/api/takeaway_profit")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_takeaway_profits(test_async_client, test_async_redis_client):
    # create takeaway_profit for every strategy
    await create_open_trades(
        test_async_redis_client=test_async_redis_client,
        users=1,
        strategies=10,
        trades=10,
        take_away_profit=True,
        test_async_redis_client=test_async_redis_client,
    )

    async with Database() as async_session:
        takeaway_profit_query = await async_session.scalars(
            select(TakeAwayProfitModel.id, TakeAwayProfitModel)
        )
        takeaway_profit_ids = takeaway_profit_query.all()

        response = await test_async_client.get("/api/takeaway_profit")
        assert response.status_code == 200
        assert all(
            UUID(takeaway_profit_data["id"]) in takeaway_profit_ids
            for takeaway_profit_data in response.json()
        )
