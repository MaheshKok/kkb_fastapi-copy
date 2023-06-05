from test.factory.user import UserFactory

import pytest


@pytest.mark.asyncio
async def test_trade_sql(async_session):
    user = await UserFactory(async_session=async_session)
    assert user.id is not None
