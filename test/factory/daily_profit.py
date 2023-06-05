import uuid
from datetime import datetime
from datetime import timedelta

import factory

from app.database.models import DailyProfit
from test.factory.base_factory import BaseFactory
from test.factory.strategy import StrategyFactory


class DailyProfitFactory(BaseFactory):
    class Meta:
        model = DailyProfit

    id = factory.LazyFunction(uuid.uuid4)
    profit = 12000.0
    future_profit = 36000.0
    date = factory.LazyFunction(datetime.utcnow() - timedelta(days=1))

    strategy = factory.SubFactory(StrategyFactory)
