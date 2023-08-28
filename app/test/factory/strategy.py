import uuid
from datetime import datetime
from datetime import timedelta

import factory
import pytest

from app.database.models import StrategyModel
from app.schemas.enums import PositionEnum
from app.test.factory.base_factory import AsyncSQLAlchemyFactory
from app.test.factory.create_async_session import async_session
from app.test.factory.user import UserFactory


@pytest.mark.asyncio
class StrategyFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = StrategyModel
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = async_session

    id = factory.LazyFunction(uuid.uuid4)
    exchange = "NFO"

    instrument_type = "OPTIDX"
    symbol = "BANKNIFTY"
    position = PositionEnum.LONG

    is_active = True
    name = factory.Sequence(lambda n: f"strategy_{n}")

    user = factory.SubFactory(UserFactory)
    created_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(days=n))
