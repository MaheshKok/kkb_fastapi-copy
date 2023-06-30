import secrets
import uuid

import factory
from async_factory_boy.factory.sqlalchemy import AsyncSQLAlchemyFactory

from app.database.models import BrokerModel
from test.factory.base_factory import sc_session


class BrokerFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = BrokerModel
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = sc_session

    id = factory.LazyFunction(uuid.uuid4)
    access_token = factory.Sequence(lambda n: secrets.token_hex(128))
    name = "ALICEBLUE"
    username = factory.Sequence(lambda n: str(secrets.randbits(20)))
    password = factory.Sequence(lambda n: secrets.token_hex(8))
    api_key = factory.Sequence(lambda n: secrets.token_hex(50))
    app_id = factory.Sequence(lambda n: secrets.token_hex(8))
    totp = factory.Sequence(lambda n: secrets.token_hex(16))
