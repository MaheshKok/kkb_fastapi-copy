import uuid
from datetime import timedelta

import factory
import pytest

from app.database.models import Strategy
from test.factory.base_factory import BaseFactory
from test.factory.user import UserFactory


def create_user():
    return UserFactory()


@pytest.mark.asyncio
class StrategyFactory(BaseFactory):
    class Meta:
        model = Strategy

    id = factory.LazyFunction(uuid.uuid4)
    exchange = "NFO"

    instrument_type = "OPTIDX"
    symbol = "BANKNIFTY"

    is_active = True
    name = factory.Sequence(lambda n: f"strategy_{n}")

    user = factory.SubFactory(UserFactory)

    @factory.lazy_attribute
    def created_at(self):
        return self.user.created_at + timedelta(days=1)
