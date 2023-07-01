import asyncio
import io
import json
import logging
from datetime import datetime

import aioredis
import httpx
import pandas as pd
import pytest as pytest
import pytest_asyncio
from fastapi_sa.database import db
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import QueuePool

from app.api.utils import get_current_and_next_expiry
from app.core.config import get_config
from app.create_app import get_app
from app.cron.update_fno_expiry import update_expiry_list
from app.database import Base
from app.database.base import engine_kw
from app.database.base import get_db_url
from app.database.models import StrategyModel
from app.tasks.utils import get_monthly_expiry_date
from app.utils.constants import ConfigFile
from test.unit_tests.test_data import get_test_post_trade_payload
from test.utils import create_pre_db_data


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


@pytest.fixture(scope="session", autouse=True)
async def setup_redis():
    test_config = get_config(ConfigFile.TEST)
    _test_async_redis_client = await aioredis.StrictRedis.from_url(
        test_config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
    )
    # update redis with necessary data i.e expiry list, option chain etc
    await update_expiry_list(test_config, "INDX OPT")

    logging.info(f"Updated redis with expiry list: {datetime.now()}")
    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        _test_async_redis_client, datetime.now().date()
    )

    prod_config = get_config()
    prod_async_redis_client = await aioredis.StrictRedis.from_url(
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

    monthly_expiry = await get_monthly_expiry_date(_test_async_redis_client)
    if monthly_expiry:
        keys.append(f"BANKNIFTY {monthly_expiry} FUT")
        keys.append(f"NIFTY {monthly_expiry} FUT")

    start_time = datetime.now()
    logging.info("start updating redis with option_chain")
    all_option_chain = {}

    # Queue up hgetall commands
    async with prod_async_redis_client.pipeline() as pipe:
        for key in keys:
            pipe.hgetall(key)
        option_chains = await pipe.execute()

    # Process results
    for key, option_chain in zip(keys, option_chains):
        if option_chain:
            all_option_chain[key] = option_chain

    logging.info(f"Pulled option chain from prod redis in [ {datetime.now() - start_time} ]")

    start_time = datetime.now()
    # Queue up hset commands
    async with _test_async_redis_client.pipeline() as pipe:
        for key, option_chain in all_option_chain.items():
            if "FUT" in key:
                # For future option chain first and second argument are same
                pipe.hset(key, key, option_chain["FUT"])
            else:
                for strike, premium in option_chain.items():
                    pipe.hset(key, strike, premium)
        await pipe.execute()

    logging.info(
        f"Time taken to update redis with option chain: [ {datetime.now() - start_time} ]"
    )

    # Choose the column to be used as the key
    key_column = "Formatted Ins Name"

    url = "https://v2api.aliceblueonline.com/restpy/static/contract_master/NFO.csv"
    response = await httpx.AsyncClient().get(url)
    data_stream = io.StringIO(response.text)
    try:
        df = pd.read_csv(data_stream)
        full_name_row_dict = {}
        for key, value in df.set_index(key_column).T.to_dict().items():
            if "BANKNIFTY" in key or "NIFTY" in key:
                full_name_row_dict[key] = json.dumps(value)
    except Exception as e:
        logging.error(f"Error while reading csv: {e}")

    logging.info("Start setting master contract in Redis")
    start_time = datetime.now()

    # Split the dictionary into smaller chunks
    chunk_size = 10000
    dict_chunks = [
        dict(list(full_name_row_dict.items())[i : i + chunk_size])
        for i in range(0, len(full_name_row_dict), chunk_size)
    ]

    # Use a pipeline to set each chunk of key-value pairs in Redis
    async with _test_async_redis_client.pipeline() as pipe:
        for chunk in dict_chunks:
            for key, value in chunk.items():
                pipe.set(key, value)
        await pipe.execute()

    logging.info(f"Time taken to set master contract in redis: [ {datetime.now() - start_time} ]")


@pytest.fixture(scope="session", autouse=True)
def event_loop(request):
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    logging.info("loop created")
    yield loop
    logging.info("loop closed")
    loop.close()


# @pytest_asyncio.fixture(scope="function", autouse=True)  # (scope="session")
# async def db_session() -> AsyncSession:
#     async with engine.begin() as connection:
#         await connection.run_sync(Base.metadata.drop_all)
#         await connection.run_sync(Base.metadata.create_all)
#
#         async with async_session(bind=connection) as session:
#             yield session
#             await session.flush()
#             await session.rollback()


@pytest.fixture(scope="session")
def test_config():
    config = get_config(ConfigFile.TEST)
    return config


@pytest_asyncio.fixture(scope="function")
async def test_async_redis_client():
    test_config = get_config(ConfigFile.TEST)
    _test_async_redis_client = await aioredis.StrictRedis.from_url(
        test_config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
    )
    logging.info("test redis client created")
    yield _test_async_redis_client
    logging.info("test redis client created")


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
            logging.info("test db engine created")
            yield engine
            logging.info("test db engine closed")
        except Exception as e:  # pragma: no cover
            await trans.rollback()
            raise e
        finally:
            logging.info("commiting transaction")
            await trans.commit()
            logging.info("committed transaction")

    await engine.dispose()
    logging.info("test db engine disposed")


@pytest_asyncio.fixture(scope="function", autouse=True)
async def db_cleanup(test_async_engine):
    async with test_async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    logging.info("tables created")
    yield

    async with test_async_engine.begin() as conn:
        logging.info("tables dropping")
        await conn.run_sync(Base.metadata.drop_all)
        logging.info("tables created")


@pytest.fixture()
def db_session_ctx(test_config):
    async_db_url = get_db_url(test_config)
    db.init(async_db_url, engine_kw=engine_kw)

    """db session context"""
    token = db.set_session_ctx()
    logging.info("db session context created")
    yield
    db.reset_session_ctx(token)
    logging.info("db session context closed")


@pytest.fixture(autouse=True)
async def test_async_session(db_session_ctx):
    """session fixture"""
    async with db.session.begin():
        logging.info("test db session created")
        yield db.session
        logging.info("test db session closed")


@pytest_asyncio.fixture(scope="function")
async def test_app(test_async_redis_client):
    app = get_app(ConfigFile.TEST)  # pragma: no cover
    app.state.async_redis_client = test_async_redis_client  # pragma: no cover
    logging.info("test app created")
    yield app
    logging.info("test app closed")

    # cleanup redis after test
    # remove all stored trades and leave option chain and expiry list for other unit tests
    async with test_async_redis_client.pipeline() as pipe:
        keys = await test_async_redis_client.keys()
        for key in keys:
            if "BANKNIFTY" in key or "NIFTY" in key or "expiry_list" in key:
                continue
            test_async_redis_client.delete(key)
        await pipe.execute()
        logging.info("redis cleaned up")


@pytest_asyncio.fixture(scope="function")
async def test_async_client(test_app):
    # TODO: figure it out how to dynamically set the base_url
    async with AsyncClient(
        app=test_app, base_url="http://localhost:8080/"
    ) as ac:  # pragma: no cover
        logging.info("test httpx async client created")
        yield ac
        logging.info("test httpx async client closed")


@pytest_asyncio.fixture(scope="function")
async def buy_task_payload_dict(test_async_redis_client):
    post_trade_payload = get_test_post_trade_payload()

    await create_pre_db_data(users=1, strategies=1, trades=10)
    # query database for stragey

    async with db():
        fetch_strategy_query_ = await db.session.execute(select(StrategyModel))
        strategy_model = fetch_strategy_query_.scalars().one_or_none()

        (
            current_expiry_date,
            next_expiry_date,
            is_today_expiry,
        ) = await get_current_and_next_expiry(test_async_redis_client, datetime.now().date())

        post_trade_payload["strategy_id"] = strategy_model.id
        post_trade_payload["expiry"] = current_expiry_date

        return post_trade_payload


# @pytest_asyncio.fixture(scope="function", autouse=True)
# async def patch_redis_option_chain(test_app, monkeypatch):
#     async def mock_hgetall(key):
#         # You can perform additional checks or logic based on the key if needed
#         if "CE" in key:
#             return get_ce_option_chain()
#         elif "PE" in key:
#             return get_pe_option_chain()
#         else:
#             return {"FUT": "44110.10"}
#
#     mock_redis = MagicMock()
#     mock_redis.hgetall = AsyncMock(side_effect=mock_hgetall)
#     test_app.state.async_redis_client = mock_redis
#     # monkeypatch.setattr("app.utils.option_chain.async_redis_client", mock_redis)
#     return mock_redis
#
#
# @pytest_asyncio.fixture(scope="function", autouse=True)
# async def patch_redis_expiry_list(test_app, monkeypatch):
#     mock_redis = MagicMock()
#     mock_redis.get = AsyncMock(return_value='["10 JUN 2023", "15 JUN 2023"]')
#     test_app.state.async_redis_client = mock_redis
#     # monkeypatch.setattr("app.api.utils.async_redis_client", mock_redis)
#     return mock_redis


# @pytest_asyncio.fixture(scope="function")
# async def patch_redis_delete_ongoing_trades(monkeypatch):
#     mock_redis = MagicMock()
#     mock_redis.delete = AsyncMock(return_value=True)
#     monkeypatch.setattr("tasks.tasks.async_redis_client", mock_redis)
#     return mock_redis
#
#
# @pytest_asyncio.fixture(scope="function")
# async def patch_redis_add_trades_to_new_key(monkeypatch):
#     mock_redis = MagicMock()
#     mock_redis.exists = AsyncMock(return_value=False)
#     mock_redis.lpush = AsyncMock(return_value=True)
#     monkeypatch.setattr("tasks.tasks.async_redis_client", mock_redis)
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
#     monkeypatch.setattr("tasks.tasks.async_redis_client", mock_redis)
#     return mock_redis
