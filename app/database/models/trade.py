import uuid
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.database.models import StrategyModel


class TradeModel(Base):
    __tablename__ = "trade"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument = Column(String, nullable=False, index=True)

    quantity = Column(Integer, default=25)
    position = Column(String, nullable=False, index=True)

    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    profit = Column(Float, nullable=True)

    future_entry_price_received = Column(Float, nullable=True)
    future_entry_price = Column(Float, nullable=True)
    future_exit_price = Column(Float, nullable=True)
    future_profit = Column(Float, nullable=True)

    entry_received_at = Column(TIMESTAMP(timezone=True), nullable=False)
    entry_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.now())
    exit_received_at = Column(TIMESTAMP(timezone=True), nullable=True)
    exit_at = Column(TIMESTAMP(timezone=True), nullable=True)

    strike = Column(Float, nullable=True)
    option_type = Column(String, nullable=True, index=True)
    expiry = Column(Date, index=True)

    strategy_id = Column(
        UUID(as_uuid=True), ForeignKey("strategy.id"), nullable=False, index=True
    )
    strategy = relationship(StrategyModel, backref="trades")
