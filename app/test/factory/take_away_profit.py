import uuid
from datetime import datetime
from datetime import timedelta

import factory

from app.database.models import TakeAwayProfitModel
from app.test.factory.base_factory import AsyncSQLAlchemyFactory
from app.test.factory.create_async_session import async_session
from app.test.factory.strategy import StrategyFactory


class TakeAwayProfitFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = TakeAwayProfitModel
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = async_session

    id = factory.LazyFunction(uuid.uuid4)
    profit = 12000.0
    future_profit = 36000.0
    strategy = factory.SubFactory(StrategyFactory)

    created_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(days=2))
    updated_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(hours=4))
    total_trades = 30
