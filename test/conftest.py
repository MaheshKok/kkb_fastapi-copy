from datetime import datetime
from unittest.mock import AsyncMock

import aioredis
import pytest as pytest
import pytest_asyncio
from asynctest import MagicMock
from httpx import AsyncClient
from sqlalchemy import QueuePool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.utils import get_current_and_next_expiry
from app.api.utils import get_expiry_list
from app.core.config import get_config
from app.cron.update_fno_expiry import update_expiry_list
from app.database import Base
from app.database.base import get_db_url
from app.setup_app import get_application
from app.utils.constants import ConfigFile
from test.unit_tests.test_data import get_ce_option_chain
from test.unit_tests.test_data import get_pe_option_chain


@pytest.fixture(scope="session", autouse=True)
async def setup_redis():
    # try to make this fixture as session based instead of function based
    test_config = get_config(ConfigFile.TEST)
    _test_async_redis = await aioredis.StrictRedis.from_url(
        test_config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
    )
    # update redis with necessary data i.e expiry list, option chain etc
    await update_expiry_list(test_config, "INDX OPT")

    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        _test_async_redis, datetime.now().date()
    )

    prod_config = get_config()
    prod_async_redis = await aioredis.StrictRedis.from_url(
        prod_config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
    )
    # add keys for future price as well
    keys = [
        f"BANKNIFTY {current_expiry_date} CE",
        f"BANKNIFTY {current_expiry_date} PE",
        f"BANKNIFTY {next_expiry_date} CE",
        f"BANKNIFTY {next_expiry_date} PE",
        f"NIFTY {current_expiry_date} CE",
        f"NIFTY {current_expiry_date} PE",
        f"NIFTY {next_expiry_date} CE",
        f"NIFTY {next_expiry_date} PE",
    ]

    monthly_expiry = None
    current_month_number = datetime.now().date().month
    expiry_list = await get_expiry_list(_test_async_redis)
    for _, expiry_date in enumerate(expiry_list):
        if expiry_date.month > current_month_number:
            break
        monthly_expiry = expiry_date

    if monthly_expiry:
        keys.append(f"BANKNIFTY {monthly_expiry} FUT")
        keys.append(f"NIFTY {monthly_expiry} FUT")

    start_time = datetime.now()
    print(f"start updating redis with option_chain: {start_time}")
    all_option_chain = {}
    async with prod_async_redis.pipeline() as pipe:
        for key in keys:
            option_chain = await prod_async_redis.hgetall(key)
            if option_chain:
                all_option_chain[key] = option_chain
    await pipe.execute()

    async with _test_async_redis.pipeline() as pipe:
        for key, option_chain in all_option_chain.items():
            for strike, premium in option_chain.items():
                await _test_async_redis.hset(key, strike, premium)
    await pipe.execute()

    print(f"Time taken to update redis: {datetime.now() - start_time}")


@pytest_asyncio.fixture(scope="function")
async def test_async_redis():
    # try to make this fixture as session based instead of function based
    test_config = get_config(ConfigFile.TEST)
    _test_async_redis = await aioredis.StrictRedis.from_url(
        test_config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
    )
    # # update redis with necessary data i.e expiry list, option chain etc
    # await update_expiry_list(test_config, "INDX OPT")
    #
    # current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
    #     _test_async_redis, datetime.now().date()
    # )
    #
    # prod_config = get_config()
    # prod_async_redis = await aioredis.StrictRedis.from_url(
    #     prod_config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
    # )
    # # add keys for future price as well
    # keys = [
    #     f"BANKNIFTY {current_expiry_date} CE",
    #     f"BANKNIFTY {current_expiry_date} PE",
    #     f"BANKNIFTY {next_expiry_date} CE",
    #     f"BANKNIFTY {next_expiry_date} PE",
    #     f"NIFTY {current_expiry_date} CE",
    #     f"NIFTY {current_expiry_date} PE",
    #     f"NIFTY {next_expiry_date} CE",
    #     f"NIFTY {next_expiry_date} PE",
    # ]
    #
    # monthly_expiry = None
    # current_month_number = datetime.now().date().month
    # expiry_list = await get_expiry_list(_test_async_redis)
    # for index, expiry_date in enumerate(expiry_list):
    #     if expiry_date.month > current_month_number:
    #         break
    #     monthly_expiry = expiry_date
    #
    # if monthly_expiry:
    #     keys.append(f"BANKNIFTY {monthly_expiry} FUT")
    #     keys.append(f"NIFTY {monthly_expiry} FUT")
    #
    # start_time = datetime.now()
    # print(f"start updating redis with option_chain: {start_time}")
    # all_option_chain = {}
    # async with prod_async_redis.pipeline() as pipe:
    #     for key in keys:
    #         option_chain = await prod_async_redis.hgetall(key)
    #         if option_chain:
    #             all_option_chain[key] = option_chain
    # await pipe.execute()
    #
    # async with _test_async_redis.pipeline() as pipe:
    #     for key, option_chain in all_option_chain.items():
    #         for strike, premium in option_chain.items():
    #             await _test_async_redis.hset(key, strike, premium)
    # await pipe.execute()
    #
    # print(f"Time taken to update redis: {datetime.now() - start_time}")
    yield _test_async_redis


@pytest.fixture(scope="session")
def test_config():
    config = get_config(ConfigFile.TEST)
    return config


@pytest_asyncio.fixture(scope="function")
async def test_async_engine(test_config):
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
async def db_cleanup(test_async_engine):
    async with test_async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with test_async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def test_async_session_maker(test_async_engine):
    async_session_ = sessionmaker(test_async_engine, class_=AsyncSession, expire_on_commit=True)
    yield async_session_


@pytest_asyncio.fixture(scope="function")
async def test_async_session(test_async_session_maker):
    async with test_async_session_maker() as async_session:
        try:
            yield async_session
            await async_session.commit()
        except Exception as e:  # pragma: no cover
            await async_session.rollback()
            raise e
        finally:
            await async_session.close()


@pytest_asyncio.fixture(scope="function")
async def test_app(test_async_session_maker, test_async_redis):
    app = get_application(ConfigFile.TEST)  # pragma: no cover
    app.state.async_session_maker = test_async_session_maker  # pragma: no cover
    app.state.async_redis = test_async_redis  # pragma: no cover
    yield app

    # cleanup redis after test
    # remove all stored trades and leave option chain and expiry list for other unit tests
    async with test_async_redis.pipeline() as pipe:
        for key in await test_async_redis.keys():
            if "BANKNIFTY" in key or "NIFTY" in key or "expiry_list" in key:
                continue
            await test_async_redis.delete(key)
    await pipe.execute()


@pytest_asyncio.fixture(scope="function")
async def test_async_client(test_app):
    # TODO: figure it out how to dynamically set the base_url
    async with AsyncClient(
        app=test_app, base_url="http://localhost:8080/"
    ) as ac:  # pragma: no cover
        yield ac


@pytest_asyncio.fixture(scope="function", autouse=True)
async def patch_redis_option_chain(test_app, monkeypatch):
    async def mock_hgetall(key):
        # You can perform additional checks or logic based on the key if needed
        if "CE" in key:
            return get_ce_option_chain()
        elif "PE" in key:
            return get_pe_option_chain()
        else:
            return {"FUT": "44110.10"}

    mock_redis = MagicMock()
    mock_redis.hgetall = AsyncMock(side_effect=mock_hgetall)
    test_app.state.async_redis = mock_redis
    # monkeypatch.setattr("app.utils.option_chain.async_redis", mock_redis)
    return mock_redis


@pytest_asyncio.fixture(scope="function", autouse=True)
async def patch_redis_expiry_list(test_app, monkeypatch):
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value='["10 JUN 2023", "15 JUN 2023"]')
    test_app.state.async_redis = mock_redis
    # monkeypatch.setattr("app.api.utils.async_redis", mock_redis)
    return mock_redis


# @pytest_asyncio.fixture(scope="function")
# async def patch_redis_delete_ongoing_trades(monkeypatch):
#     mock_redis = MagicMock()
#     mock_redis.delete = AsyncMock(return_value=True)
#     monkeypatch.setattr("tasks.tasks.async_redis", mock_redis)
#     return mock_redis
#
#
# @pytest_asyncio.fixture(scope="function")
# async def patch_redis_add_trades_to_new_key(monkeypatch):
#     mock_redis = MagicMock()
#     mock_redis.exists = AsyncMock(return_value=False)
#     mock_redis.lpush = AsyncMock(return_value=True)
#     monkeypatch.setattr("tasks.tasks.async_redis", mock_redis)
#     return mock_redis
#
#
# @pytest_asyncio.fixture(scope="function")
# async def patch_redis_add_trade_to_ongoing_trades(test_async_session, monkeypatch):
#     await create_open_trades(async_session=test_async_session, trades=10, ce_trade=True)
#     fetch_trades_query_ = await test_async_session.execute(select(TradeModel))
#     trade_models = fetch_trades_query_.scalars().all()
#     mock_redis = MagicMock()
#     mock_redis.exists = AsyncMock(return_value=True)
#     mock_redis.lrange = AsyncMock(
#         return_value=[
#             RedisTradeSchema.from_orm(trade_model).json() for trade_model in trade_models
#         ]
#     )
#     mock_redis.delete = AsyncMock(return_value=True)
#     mock_redis.lpush = AsyncMock(return_value=True)
#     monkeypatch.setattr("tasks.tasks.async_redis", mock_redis)
#     return mock_redis
