import uuid
from datetime import datetime
from datetime import timedelta

import factory

from app.database.models import Strategy
from test.factory.base_factory import BaseFactory
from test.factory.user import UserFactory


class StrategyFactory(BaseFactory):
    class Meta:
        model = Strategy

    id = factory.LazyFunction(uuid.uuid4)
    exchange = "NFO"

    instrument_type = "OPTIDX"
    created_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(days=n))
    symbol = "BANKNIFTY"

    is_active = True
    name = factory.Sequence(lambda n: f"strategy_{n}")

    user = factory.SubFactory(UserFactory)
    user_id = factory.LazyAttribute(lambda obj: obj.user.id)
