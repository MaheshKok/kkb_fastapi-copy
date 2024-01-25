# Create data storage
import uuid

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class TakeAwayProfitModel(Base):
    __tablename__ = "take_away_profit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profit = Column(Float, nullable=True)
    future_profit = Column(Float, nullable=True, default=None)
    strategy_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategy.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=True)
    total_trades = Column(Integer, nullable=False)
