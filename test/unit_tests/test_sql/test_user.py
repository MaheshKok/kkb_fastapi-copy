import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database.models import User
from test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_user_factory(test_async_session):
    for _ in range(10):
        await UserFactory(async_session=test_async_session)

    result = await test_async_session.execute(select(User))
    assert len(result.all()) == 10


@pytest.mark.asyncio
async def test_user_factory_invalid_async_session(test_async_session):
    with pytest.raises(SQLAlchemyError) as exc:
        user = await UserFactory(async_session=test_async_session)
        assert user is not None

        # try to create user with same id
        await UserFactory(async_session=test_async_session, id=user.id)

    assert exc.typename == "IntegrityError"
