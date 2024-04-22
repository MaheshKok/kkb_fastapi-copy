import uuid
from datetime import datetime

from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.pydantic_models.enums import PositionEnum


class StrategyDBModel(Base):
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

    premium = Column(Float, nullable=True, default=350.0)

    funds = Column(Float, nullable=False)
    future_funds = Column(Float, nullable=True)
    min_quantity = Column(Float, nullable=False)
    margin_for_min_quantity = Column(Float, nullable=False)
    incremental_step_size = Column(Float, nullable=False)
    compounding = Column(Boolean, nullable=False, default=True)
    contracts = Column(Float, nullable=True)
    funds_usage_percent = Column(Float, nullable=False, default=1.0)

    only_on_expiry = Column(Boolean, nullable=False, server_default="False")
    broker_id = Column(
        UUID(as_uuid=True), ForeignKey("broker.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )

    daily_profit_db_models = relationship(
        "DailyProfitDBModel", backref="strategy", cascade="all, delete"
    )
    trades = relationship("TradeDBModel", back_populates="strategy", cascade="all, delete")
