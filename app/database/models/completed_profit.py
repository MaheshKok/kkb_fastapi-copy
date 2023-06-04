# Create data storage
import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import db


class CompletedProfit(db.Model):
    __tablename__ = "completed_profit"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profit = db.Column(db.Float, nullable=True)
    futures_profit = db.Column(db.Float, nullable=True, default=0.0)
    strategy_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("strategy.id"), nullable=False, index=True
    )

    created_at = db.Column(db.DateTime, nullable=False, default=db.func.now())
    updated_at = db.Column(db.DateTime, nullable=True)
    total_trades = db.Column(db.Integer, nullable=False)
    strategy = relationship("Strategy", backref="completed_profit")
