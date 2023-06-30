import uuid
from datetime import datetime
from datetime import timedelta

import factory
import pytest
from async_factory_boy.factory.sqlalchemy import AsyncSQLAlchemyFactory

from app.database.models import StrategyModel
from app.schemas.enums import PositionEnum
from test.factory.base_factory import sc_session
from test.factory.user import UserFactory


@pytest.mark.asyncio
class StrategyFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = StrategyModel
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = sc_session

    id = factory.LazyFunction(uuid.uuid4)
    exchange = "NFO"

    instrument_type = "OPTIDX"
    symbol = "BANKNIFTY"
    position = PositionEnum.LONG

    is_active = True
    name = factory.Sequence(lambda n: f"strategy_{n}")

    user = factory.SubFactory(UserFactory)
    created_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(days=n))
