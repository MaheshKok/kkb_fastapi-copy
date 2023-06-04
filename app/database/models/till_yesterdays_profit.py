# Create data storage
import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.base import db


class TillYesterdaysProfit(db.Model):
    __tablename__ = "till_yesterdays_profit"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profit = db.Column(db.Float, nullable=True)
    strategy_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("strategy.id"), nullable=False, index=True
    )
    strategy = relationship("Strategy", backref="trades")

    date = db.Column(db.Date, nullable=False)
