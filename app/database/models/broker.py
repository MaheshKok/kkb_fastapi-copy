import uuid

from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Broker(Base):
    __tablename__ = "broker"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    access_token = Column(String, nullable=False)
    name = Column(String, nullable=False)
    username = Column(String, nullable=False)
    password = Column(String, nullable=False)
    api_key = Column(String, nullable=True)
    app_id = Column(String, nullable=True)
    totp = Column(String, nullable=True)

    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    user = relationship("User", backref="brokers")
