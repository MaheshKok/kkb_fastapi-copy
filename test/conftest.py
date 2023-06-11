from datetime import timedelta
from unittest.mock import AsyncMock

import pytest as pytest
import pytest_asyncio
from asynctest import MagicMock
from httpx import AsyncClient
from sqlalchemy import QueuePool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_config
from app.database import Base
from app.database.base import get_db_url
from app.setup_app import get_application
from app.utils.constants import ConfigFile
from test.factory.strategy import StrategyFactory
from test.factory.take_away_profit import TakeAwayProfitFactory
from test.factory.trade import TradeFactory
from test.factory.user import UserFactory
from test.unit_tests.test_data import get_ce_option_chain
from test.unit_tests.test_data import get_pe_option_chain


@pytest.fixture(scope="function")
def test_config():
    config = get_config(ConfigFile.TEST)
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
        except Exception as e:  # pragma: no cover
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
        except Exception as e:  # pragma: no cover
            await async_session.rollback()
            raise e
        finally:
            await async_session.close()


@pytest_asyncio.fixture(scope="function")
async def async_client(async_session_maker):
    app = get_application(ConfigFile.TEST)  # pragma: no cover
    app.state.async_session_maker = async_session_maker  # pragma: no cover

    # TODO: figure it out how to dynamically set the base_url
    async with AsyncClient(app=app, base_url="http://localhost:8080/") as ac:  # pragma: no cover
        yield ac


async def create_ecosystem(
    async_session, users=1, strategies=1, trades=10, take_away_profit=False, daily_profit=0
):
    for _ in range(users):
        user = await UserFactory(async_session=async_session)

        for _ in range(strategies):
            strategy = await StrategyFactory(
                async_session=async_session,
                user=user,
                created_at=user.created_at + timedelta(days=1),
            )

            for _ in range(trades):
                _ = await TradeFactory(async_session=async_session, strategy=strategy)

            if take_away_profit:
                TakeAwayProfitFactory(
                    async_session=async_session, strategy=strategy, trades=trades
                )


@pytest_asyncio.fixture(scope="function")
async def patch_redis_option_chain(monkeypatch):
    async def mock_hgetall(key):
        # You can perform additional checks or logic based on the key if needed
        if "CE" in key:
            return get_ce_option_chain()
        else:
            return get_pe_option_chain()

    mock_redis = MagicMock()
    mock_redis.hgetall = AsyncMock(side_effect=mock_hgetall)

    monkeypatch.setattr("app.utils.option_chain.redis", mock_redis)
