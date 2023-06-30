import uuid
from datetime import datetime
from datetime import timedelta

import factory
from async_factory_boy.factory.sqlalchemy import AsyncSQLAlchemyFactory

from app.database.models import TakeAwayProfit
from test.factory.base_factory import sc_session
from test.factory.strategy import StrategyFactory


class TakeAwayProfitFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = TakeAwayProfit
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = sc_session

    id = factory.LazyFunction(uuid.uuid4)
    profit = 12000.0
    future_profit = 36000.0
    strategy = factory.SubFactory(StrategyFactory)

    created_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(days=2))
    updated_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(hours=4))
    total_trades = 30
