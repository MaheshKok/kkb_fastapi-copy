from app.database.base import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer(), primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password = db.Column(db.String(), nullable=False)
    email = db.Column(db.String(50), nullable=False, unique=True)
    is_active = db.Column(db.Boolean(), default=True)
    is_superuser = db.Column(db.Boolean(), default=False)
    created_at = db.Column(db.DateTime(), nullable=False)
    updated_at = db.Column(db.DateTime(), nullable=False)
