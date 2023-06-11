import pytest
from factory.alchemy import SQLAlchemyModelFactory
from sqlalchemy.exc import SQLAlchemyError


@pytest.mark.asyncio
class BaseFactory(SQLAlchemyModelFactory):
    @classmethod
    async def _create(cls, model_class, async_session=None, *args, **kwargs):
        instance = model_class(*args, **kwargs)
        async_session.add(instance)
        try:
            await async_session.commit()
            await async_session.refresh(instance)
            return instance
        except SQLAlchemyError as e:
            await async_session.rollback()
            raise e
