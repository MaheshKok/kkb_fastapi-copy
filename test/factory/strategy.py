import uuid
from datetime import datetime
from datetime import timedelta

import factory
import pytest

from app.database.models import StrategyModel
from app.schemas.enums import PositionEnum
from test.factory import UserFactory
from test.factory.base_factory import BaseFactory


@pytest.mark.asyncio
class StrategyFactory(BaseFactory):
    class Meta:
        model = StrategyModel

    id = factory.LazyFunction(uuid.uuid4)
    exchange = "NFO"

    instrument_type = "OPTIDX"
    symbol = "BANKNIFTY"
    position = PositionEnum.LONG

    is_active = True
    name = factory.Sequence(lambda n: f"strategy_{n}")

    user = factory.SubFactory(UserFactory)
    created_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(days=n))
