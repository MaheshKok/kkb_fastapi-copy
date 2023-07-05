import uuid
from datetime import datetime
from datetime import timedelta

import factory

from app.database.models import DailyProfitModel
from test.factory.base_factory import AsyncSQLAlchemyFactory
from test.factory.create_async_session import async_session
from test.factory.strategy import StrategyFactory


class DailyProfitFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = DailyProfitModel
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = async_session

    id = factory.LazyFunction(uuid.uuid4)
    profit = 12000.0
    future_profit = 36000.0
    date = factory.LazyFunction(datetime.utcnow() - timedelta(days=1))

    strategy = factory.SubFactory(StrategyFactory)
