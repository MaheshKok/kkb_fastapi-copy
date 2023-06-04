import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import db


class Trade(db.Model):
    __tablename__ = "trade"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quantity = db.Column(db.Integer, default=25)
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
