import uuid
from datetime import datetime
from datetime import timedelta

import factory
from async_factory_boy.factory.sqlalchemy import AsyncSQLAlchemyFactory

from app.database.models import DailyProfit
from test.conftest import sc_session
from test.factory.strategy import StrategyFactory


class DailyProfitFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = DailyProfit
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = sc_session

    id = factory.LazyFunction(uuid.uuid4)
    profit = 12000.0
    future_profit = 36000.0
    date = factory.LazyFunction(datetime.utcnow() - timedelta(days=1))

    strategy = factory.SubFactory(StrategyFactory)
