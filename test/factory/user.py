import uuid
from datetime import datetime
from datetime import timedelta

import factory
from factory import Sequence

from app.database.models import User
from test.factory.base_factory import BaseFactory


class UserFactory(BaseFactory):
    class Meta:
        model = User

    id = uuid.uuid4()
    email = Sequence(lambda n: f"email{n}@example.com")
    access_token = Sequence(lambda n: f"access_token_{n}")
    refresh_token = Sequence(lambda n: f"refresh_token_{n}")
    token_expiry = Sequence(lambda n: datetime.utcnow() + timedelta(days=n))
    created_at = Sequence(lambda n: datetime.utcnow() - timedelta(days=n))
    updated_at = factory.LazyFunction(datetime.utcnow)
