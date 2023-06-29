import uuid
from datetime import datetime

from fastapi_manager import Manager
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.schemas.enums import PositionEnum


class StrategyModel(Base):
    """
    RULES:
    1. Strategy can be either LONG or SHORT, it cannot be both
          i.e if its LONG then CE or PE will be bought and if its SHORT then CE or PE will be sold
    2. Only one symbol is allowed per Strategy like Banknifty or Nifty50

    """

    __tablename__ = "strategy"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange = Column(String, nullable=False, index=True, default="NFO")

    instrument_type = Column(String, nullable=False, index=True)
    # NULL for future and either LONG or SHORT for options
    position = Column(String, nullable=True, default=PositionEnum.LONG)
    # Timestamp when strategy is created
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.now())
    symbol = Column(String, nullable=False, index=True)

    is_active = Column(Boolean, default=True)
    # strategy details
    name = Column(String, nullable=False, default="Renko Strategy Every Candle")

    broker_id = Column(UUID(as_uuid=True), ForeignKey("broker.id"), nullable=True, index=True)
    broker = relationship("BrokerModel", backref="strategies")

    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    user = relationship("User", backref="strategy_list")

    daily_profits = relationship("DailyProfit", back_populates="strategy")
    take_away_profit = relationship("TakeAwayProfit", back_populates="strategy")


class StrategyManager(Manager[StrategyModel]):
    pass
