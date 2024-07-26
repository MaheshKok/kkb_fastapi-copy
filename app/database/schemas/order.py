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


class OrderDBModel(Base):
    __tablename__ = "order"

    unique_order_id = Column(UUID(as_uuid=True), primary_key=True)
    order_id = Column(String, nullable=False)
    status = Column(String, nullable=True)
    orderstatus = Column(String, nullable=True)
    instrument = Column(String, nullable=False, index=True)
    quantity = Column(Integer, default=25, nullable=False)

    future_entry_price_received = Column(Float, nullable=False)

    entry_received_at = Column(TIMESTAMP(timezone=True), nullable=False)
    entry_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.now())

    strike = Column(Float, nullable=True)
    option_type = Column(String, nullable=True, index=True)
    executed_price = Column(Float, nullable=True)
    expiry = Column(Date, index=True, nullable=False)
    action = Column(String, nullable=False)
    entry_exit = Column(String, nullable=False, index=True)
    text = Column(String, nullable=True)
    trade_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trade.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    trade = relationship("TradeDBModel", back_populates="orders")

    strategy_id = Column(
        UUID(as_uuid=True),
        ForeignKey("strategy.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    strategy = relationship("StrategyDBModel", back_populates="orders")
