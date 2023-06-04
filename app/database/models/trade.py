import uuid
from datetime import datetime

from pydantic import ValidationError
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
from app.schemas.enums import ActionEnum
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum


class Trade(Base):
    __tablename__ = "trade"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument = Column(String, nullable=False, index=True)

    quantity = Column(Integer, default=25)
    position = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False, index=True)

    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    profit = Column(Float, nullable=True)

    future_received_entry_price = Column(Float, nullable=True)
    future_entry_price = Column(Float, nullable=True)
    future_exit_price = Column(Float, nullable=True)
    future_profit = Column(Float, nullable=True)

    placed_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.now())
    exited_at = Column(TIMESTAMP(timezone=True), nullable=True)

    strike = Column(Float, nullable=True)
    option_type = Column(String, nullable=True, index=True)
    expiry = Column(Date, index=True)

    strategy_id = Column(
        UUID(as_uuid=True), ForeignKey("strategy.id"), nullable=False, index=True
    )
    strategy = relationship("Strategy", back_populates="trades")

    async def validate(self):
        if self.position not in [PositionEnum.LONG, PositionEnum.SHORT]:
            raise ValidationError("Invalid position")

        if self.action not in [ActionEnum.BUY, ActionEnum.SELL]:
            raise ValidationError("Invalid action")

        if self.option_type not in [OptionTypeEnum.CE, OptionTypeEnum.PE]:
            raise ValidationError("Invalid option type")

        return self
