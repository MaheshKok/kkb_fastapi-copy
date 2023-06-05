import pytest
from sqlalchemy import select

from app.database.models import User
from test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_trade_sql(async_session):
    for _ in range(10):
        await UserFactory(async_session=async_session)

    result = await async_session.execute(select(User))
    assert len(result.all()) == 10
