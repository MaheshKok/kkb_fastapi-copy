import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import UUID

from app.database.base import db


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = db.Column(db.String(), nullable=False, unique=True)

    access_token = db.Column(db.String(), nullable=False)
    refresh_token = db.Column(db.String(), nullable=False)
    token_expiry = db.Column(db.DateTime(), nullable=False)
    created_at = db.Column(db.DateTime(), default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime())
