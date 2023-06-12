import uuid
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.database.models import StrategyModel
from app.extensions.redis_cache import redis
from app.schemas.trade import RedisTradeSchema


class TradeModel(Base):
    __tablename__ = "trade"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument = Column(String, nullable=False, index=True)

    quantity = Column(Integer, default=25)
    position = Column(String, nullable=False, index=True)

    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    profit = Column(Float, nullable=True)

    future_entry_price_received = Column(Float, nullable=True)
    future_entry_price = Column(Float, nullable=True)
    future_exit_price = Column(Float, nullable=True)
    future_profit = Column(Float, nullable=True)

    entry_received_at = Column(TIMESTAMP(timezone=True), nullable=False)
    entry_at = Column(TIMESTAMP(timezone=True), nullable=False, default=datetime.now())
    exit_received_at = Column(TIMESTAMP(timezone=True), nullable=True)
    exit_at = Column(TIMESTAMP(timezone=True), nullable=True)

    strike = Column(Float, nullable=True)
    option_type = Column(String, nullable=True, index=True)
    expiry = Column(Date, index=True)

    strategy_id = Column(
        UUID(as_uuid=True), ForeignKey("strategy.id"), nullable=False, index=True
    )
    strategy = relationship(StrategyModel, backref="trades")


@event.listens_for(TradeModel, "after_insert")
async def after_insert_listener(mapper, connection, target):
    trade_key = f"{target.strategy_id}_{target.expiry}_{target.option_type}"
    trade = RedisTradeSchema.from_orm(target).json()
    if not await redis.exists(trade_key):
        await redis.lpush(trade_key, trade)
    else:
        current_trades = await redis.lrange(trade_key, 0, -1)
        updated_trades = current_trades + [trade]
        await redis.delete(trade_key)
        await redis.lpush(trade_key, *updated_trades)
