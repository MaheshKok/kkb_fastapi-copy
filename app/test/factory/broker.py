import secrets
import uuid

import factory

from app.database.schemas import BrokerDBModel
from app.test.factory.base_factory import AsyncSQLAlchemyFactory
from app.test.factory.create_async_session import async_session


class BrokerFactory(AsyncSQLAlchemyFactory):
    class Meta:
        model = BrokerDBModel
        sqlalchemy_session_persistence = "commit"
        sqlalchemy_session = async_session

    id = factory.LazyFunction(uuid.uuid4)
    access_token = factory.Sequence(lambda n: secrets.token_hex(128))
    name = "ALICEBLUE"
    username = factory.Sequence(lambda n: str(secrets.randbits(20)))
    password = factory.Sequence(lambda n: secrets.token_hex(8))
    api_key = factory.Sequence(lambda n: secrets.token_hex(50))
    app_id = factory.Sequence(lambda n: secrets.token_hex(8))
    totp = factory.Sequence(lambda n: secrets.token_hex(16))
    twoFA = factory.Sequence(lambda n: int(f"199{n}"))
