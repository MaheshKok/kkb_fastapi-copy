import uuid
from datetime import datetime
from datetime import timedelta

import factory
from factory import Sequence

from app.database.schemas import User
from app.test.factory.base_factory import AsyncSQLAlchemyFactory
from app.test.factory.create_async_session import async_session


class UserFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = User
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = async_session

    id = Sequence(lambda n: uuid.uuid4())
    email = Sequence(lambda n: f"email{uuid.uuid4()}@example.com")
    access_token = Sequence(lambda n: f"access_token_{n}")
    refresh_token = Sequence(lambda n: f"refresh_token_{n}")
    token_expiry = Sequence(lambda n: datetime.utcnow() + timedelta(days=n))
    created_at = Sequence(lambda n: datetime.utcnow() - timedelta(days=10 + n))
    updated_at = factory.LazyFunction(datetime.utcnow)
