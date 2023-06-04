import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import db


class Strategy(db.Model):
    __tablename__ = "strategy"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nfo_type = db.Column(db.String, nullable=False, index=True)

    # Timestamp when strategy is created
    created_at = db.Column(db.TIMESTAMP(timezone=True), nullable=False, default=datetime.now())
    symbol = db.Column(db.String, nullable=False, index=True)

    # strategy details
    name = db.Column(db.String, nullable=False, default="RS[R0]")

    broker_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("broker.id"), nullable=True, index=True
    )
    broker = relationship("Broker", backref="strategies")

    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("user.id"), nullable=False, index=True)
    user = relationship("User", backref="trades")

    completed_profit_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("user.id"), nullable=True, index=True
    )
    completed_profit = relationship("CompletedProfit", backref="strategy")
