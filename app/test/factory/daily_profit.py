import uuid
from datetime import datetime
from datetime import timedelta

import factory

from app.database.schemas import DailyProfitDBModel
from app.test.factory.base_factory import AsyncSQLAlchemyFactory
from app.test.factory.create_async_session import async_session
from app.test.factory.strategy import StrategyFactory


class DailyProfitFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = DailyProfitDBModel
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = async_session

    id = factory.LazyFunction(uuid.uuid4)
    todays_profit = 10000.0
    total_profit = 12000.0
    todays_future_profit = 10000.0
    total_future_profit = 36000.0
    date = factory.LazyFunction(lambda: datetime.utcnow() - timedelta(days=1))

    strategy = factory.SubFactory(StrategyFactory)
