from datetime import datetime

from app.database.base import db


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer(), primary_key=True)
    email = db.Column(db.String(), nullable=False, unique=True)

    access_token = db.Column(db.String(), nullable=False)
    refresh_token = db.Column(db.String(), nullable=False)
    token_expiry = db.Column(db.DateTime(), nullable=False)
    created_at = db.Column(db.DateTime(), default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime())
