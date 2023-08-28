import uuid
from datetime import datetime
from datetime import timedelta

import factory

from app.database.models import TradeModel
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from app.test.factory.base_factory import AsyncSQLAlchemyFactory
from app.test.factory.create_async_session import async_session
from app.test.factory.strategy import StrategyFactory


def generate_expiry_date():
    today = datetime.today()
    current_weekday = today.weekday()
    days_ahead = (3 - current_weekday) % 7  # 3 represents Thursday (Monday is 0, Sunday is 6)
    next_thursday = today + timedelta(days=days_ahead)
    return next_thursday


def generate_instrument():
    expiry_date = generate_expiry_date()
    expiry_date_formated = expiry_date.strftime("%d%b%y").upper()
    return f"BANKNIFTY{expiry_date_formated}43000CE"


class LiveTradeFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = TradeModel
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = async_session

    id = factory.LazyFunction(uuid.uuid4)
    instrument = factory.LazyFunction(generate_instrument)
    quantity = 25
    position = PositionEnum.LONG

    entry_price = 400.0

    future_entry_price_received = 44300.0
    future_entry_price = 44315.0

    entry_received_at = factory.Sequence(
        lambda n: datetime.utcnow() - timedelta(days=n, minutes=1)
    )
    entry_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(days=n))

    strike = 43000.0
    option_type = OptionTypeEnum.CE
    expiry = factory.LazyFunction(generate_expiry_date)

    strategy = factory.SubFactory(StrategyFactory)


class CompletedTradeFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = TradeModel
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = async_session

    id = factory.LazyFunction(uuid.uuid4)
    instrument = factory.LazyFunction(generate_instrument)
    quantity = 25
    position = PositionEnum.LONG

    entry_price = 400.0
    exit_price = 500.0
    profit = 2500.0

    future_entry_price_received = 44300.0
    future_entry_price = 44315.0
    future_exit_price = 44625.0
    future_profit = 7500.0

    entry_received_at = factory.Sequence(
        lambda n: datetime.utcnow() - timedelta(days=n, minutes=1)
    )
    entry_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(days=n))
    exit_received_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(minutes=1))
    exit_at = factory.LazyFunction(datetime.utcnow)

    strike = 43000.0
    option_type = OptionTypeEnum.CE
    expiry = factory.LazyFunction(generate_expiry_date)

    strategy = factory.SubFactory(StrategyFactory)
