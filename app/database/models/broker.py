import uuid

from sqlalchemy.dialects.postgresql import UUID

from app.database.base import db


class Broker(db.Model):
    __tablename__ = "broker"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    access_token = db.Column(db.String, nullable=False)
    name = db.Column(db.String, nullable=False)
    username = db.Column(db.String, nullable=False)
    password = db.Column(db.String, nullable=False)
    api_key = db.Column(db.String, nullable=True)
    app_id = db.Column(db.String, nullable=True)
    totp = db.Column(db.String, nullable=True)
