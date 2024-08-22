import uuid
from datetime import datetime

from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class CFDStrategyDBModel(Base):
    __tablename__ = "cfd_strategy"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Timestamp when strategy is created
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=True)

    instrument = Column(String, nullable=False, index=True)

    min_quantity = Column(Float, nullable=False)
    margin_for_min_quantity = Column(Float, nullable=False)
    incremental_step_size = Column(Float, nullable=False)
    max_drawdown = Column(Float, nullable=False)

    is_active = Column(Boolean, default=True)
    is_demo = Column(Boolean, default=True, nullable=False)
    funds = Column(Float, nullable=True)

    # strategy details
    name = Column(String, nullable=False, default="Renko Strategy Every Candle")

    compounding = Column(Boolean, nullable=False, default=True)
    contracts = Column(Float, nullable=True)
    funds_usage_percent = Column(Float, nullable=False, default=1.0)

    broker_id = Column(
        UUID(as_uuid=True),
        ForeignKey("broker.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
