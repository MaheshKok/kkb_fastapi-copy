import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database.models import User
from app.database.sqlalchemy_client.client import Database
from test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_user_factory():
    for _ in range(10):
        await UserFactory()

    async with Database() as async_session:
        result = await async_session.scalars(select(User))
        assert len(result.all()) == 10


@pytest.mark.asyncio
async def test_user_factory_invalid_async_session():
    with pytest.raises(SQLAlchemyError) as exc:
        user_model = await UserFactory()
        assert user_model is not None

        # try to create user with same id
        await UserFactory(id=user_model.id)

    assert exc.typename == "IntegrityError"
