import uuid
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import db
from app.schemas.enums import ActionEnum
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum


class Trade(db.Model):
    __tablename__ = "trade"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument = db.Column(db.String, nullable=False, index=True)

    quantity = db.Column(db.Integer, default=25)
    position = db.Column(db.String, nullable=False, index=True)
    action = db.Column(db.String, nullable=False, index=True)

    entry_price = db.Column(db.Float, nullable=False)
    exit_price = db.Column(db.Float, nullable=True)
    profit = db.Column(db.Float, nullable=True)

    future_received_entry_price = db.Column(db.Float, nullable=True)
    future_entry_price = db.Column(db.Float, nullable=True)
    future_exit_price = db.Column(db.Float, nullable=True)
    future_profit = db.Column(db.Float, nullable=True)

    placed_at = db.Column(db.TIMESTAMP(timezone=True), nullable=False, default=datetime.now())
    exited_at = db.Column(db.TIMESTAMP(timezone=True), nullable=True)

    strike = db.Column(db.Float, nullable=True)
    option_type = db.Column(db.String, nullable=True, index=True)
    expiry = db.Column(db.Date, index=True)

    strategy_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("strategy.id"), nullable=False, index=True
    )
    strategy = relationship("Strategy", backref="trades")

    async def validate(self):
        if self.position not in [PositionEnum.LONG, PositionEnum.SHORT]:
            raise ValidationError("Invalid position")

        if self.action not in [ActionEnum.BUY, ActionEnum.SELL]:
            raise ValidationError("Invalid action")

        if self.option_type not in [OptionTypeEnum.CE, OptionTypeEnum.PE]:
            raise ValidationError("Invalid option type")

        return self
