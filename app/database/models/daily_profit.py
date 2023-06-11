# Create data storage
import uuid

from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class DailyProfit(Base):
    __tablename__ = "daily_profit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profit = Column(Float, nullable=False)
    future_profit = Column(Float, nullable=False, default=0.0)
    strategy_id = Column(
        UUID(as_uuid=True), ForeignKey("strategy.id"), nullable=False, index=True
    )
    strategy = relationship("StrategyModel", back_populates="daily_profits")

    date = Column(Date, nullable=False)
