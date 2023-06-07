import pytest as pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import QueuePool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_config
from app.database.base import Base
from app.database.base import get_db_url
from app.setup_app import get_application
from app.utils.constants import CONFIG_FILE


@pytest.fixture(scope="function")
def test_config():
    config = get_config(CONFIG_FILE.TEST)
    return config


@pytest_asyncio.fixture(scope="function")
async def async_engine(test_config):
    async_db_url = get_db_url(test_config)
    engine = create_async_engine(
        async_db_url,
        poolclass=QueuePool,
        pool_recycle=3600,
        pool_pre_ping=True,
        pool_size=90,
        max_overflow=110,
        pool_timeout=30,
    )
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield engine
        except Exception as e:
            await trans.rollback()
            raise e
        else:
            await trans.commit()
    await engine.dispose()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def db_cleanup(async_engine):
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def async_session_maker(async_engine):
    async_session_ = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=True)
    yield async_session_


@pytest_asyncio.fixture(scope="function")
async def async_session(async_session_maker):
    async with async_session_maker() as async_session:
        try:
            yield async_session
            await async_session.commit()
        except Exception as e:
            await async_session.rollback()
            raise e
        finally:
            await async_session.close()


@pytest_asyncio.fixture(scope="function")
async def async_client(async_session_maker, test_config):
    app = await get_application(test_config)
    app.state.async_session_maker = async_session_maker

    # TODO: figure it out how to dynamically set the base_url
    async with AsyncClient(app=app, base_url="http://localhost:8080/") as ac:
        yield ac
