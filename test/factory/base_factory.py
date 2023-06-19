import pytest
from factory.alchemy import SQLAlchemyModelFactory
from fastapi_sa.database import db


@pytest.mark.asyncio
class BaseFactory(SQLAlchemyModelFactory):
    @classmethod
    async def _create(cls, model_class, *args, **kwargs):
        instance = model_class(*args, **kwargs)
        async with db():
            db.session.add(instance)
            await db.session.flush()
            return instance
