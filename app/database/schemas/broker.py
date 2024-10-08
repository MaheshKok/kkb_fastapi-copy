import uuid

from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class BrokerDBModel(Base):
    __tablename__ = "broker"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    access_token = Column(String, nullable=True)
    name = Column(String, nullable=False)
    username = Column(String, nullable=True)
    password = Column(String, nullable=True)
    api_key = Column(String, nullable=True)
    app_id = Column(String, nullable=True)
    totp = Column(String, nullable=True)
    twoFA = Column(Integer, nullable=True)

    user_id = Column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    strategydbmodel = relationship("StrategyDBModel", backref="strategy", cascade="all, delete")
