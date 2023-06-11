import uuid
from datetime import datetime
from datetime import timedelta

import factory

from app.database.models import TradeModel
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum
from test.factory.base_factory import BaseFactory
from test.factory.strategy import StrategyFactory


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


class TradeFactory(BaseFactory):
    class Meta:
        model = TradeModel

    id = factory.LazyFunction(uuid.uuid4)
    instrument = factory.LazyFunction(generate_instrument)
    quantity = 25
    position = PositionEnum.LONG

    entry_price = 400.0
    exit_price = 500.0
    profit = 2500.0

    future_received_entry_price = 44300.0
    future_entry_price = 44315.0
    future_exit_price = 44625.0
    future_profit = 7500.0

    received_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(days=n, minutes=1))
    placed_at = factory.Sequence(lambda n: datetime.utcnow() - timedelta(days=n))
    exited_at = factory.LazyFunction(datetime.utcnow)

    strike = 43000.0
    option_type = OptionTypeEnum.CE
    expiry = factory.LazyFunction(generate_expiry_date)

    strategy = factory.SubFactory(StrategyFactory)
