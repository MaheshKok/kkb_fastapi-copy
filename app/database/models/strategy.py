import uuid
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import Base


class Strategy(Base):
    __tablename__ = "strategy"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange = Column(String, nullable=False, index=True, default="NFO")

    instrument_type = Column(String, nullable=False, index=True)

    # Timestamp when strategy is created
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.now())
    symbol = Column(String, nullable=False, index=True)

    is_active = Column(Boolean, default=True)
    # strategy details
    name = Column(String, nullable=False, default="RS[R0]")

    broker_id = Column(UUID(as_uuid=True), ForeignKey("broker.id"), nullable=True, index=True)
    broker = relationship("Broker", backref="strategies")

    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    user = relationship("User", backref="strategy_list")

    trades = relationship("Trade", back_populates="strategy")

    daily_profits = relationship("DailyProfit", back_populates="strategy")
    take_away_profit = relationship("TakeAwayProfit", back_populates="strategy")

    # completed_profit_id = Column(
    #     UUID(as_uuid=True), ForeignKey("completed_profit.id"), nullable=True, index=True
    # )
    # completed_profit = relationship("CompletedProfit", backref="strategy")

    async def validate(self):
        if self.instrument_type not in ["FUTIDX", "OPTIDX"]:
            raise ValidationError("Invalid position")

        return self
