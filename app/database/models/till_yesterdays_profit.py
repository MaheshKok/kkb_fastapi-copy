# Create data storage
import uuid

from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import Base


class DailyProfit(Base):
    __tablename__ = "daily_profits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profit = Column(Float, nullable=True)
    strategy_id = Column(
        UUID(as_uuid=True), ForeignKey("strategy.id"), nullable=False, index=True
    )
    strategy = relationship("Strategy", back_populates="daily_profits")

    date = Column(Date, nullable=False)
