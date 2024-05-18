import asyncio
import logging

import aioredis
import pytest as pytest
import pytest_asyncio

# from cron.update_fno_expiry import update_expiry_list
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import QueuePool

from app.api.trade.indian_fno.utils import get_current_and_next_expiry_from_redis
from app.core.config import get_config
from app.create_app import get_app
from app.database import Base
from app.database.base import engine_kw
from app.database.base import get_db_url
from app.database.schemas import StrategyDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.broker import BrokerPydanticModel
from app.pydantic_models.enums import BrokerNameEnum
from app.pydantic_models.strategy import StrategyPydanticModel
from app.test.unit_tests.test_data import get_test_post_trade_payload
from app.test.utils import create_close_trades
from app.utils.constants import ANGELONE_BROKER
from app.utils.constants import TRADES_AND_OPTION_CHAIN_REDIS
from app.utils.constants import ConfigFile


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


@pytest.fixture(scope="session", autouse=True)
async def setup_redis():
    import io
    import json
    from datetime import datetime

    import httpx
    import pandas as pd
    from cron.download_master_contracts import push_angel_one_instruments

    from app.api.trade.indian_fno.utils import get_expiry_dict_from_alice_blue
    from app.api.trade.indian_fno.utils import get_monthly_expiry_date_from_redis
    from app.pydantic_models.enums import InstrumentTypeEnum
    from app.utils.constants import AB_NFO_CONTRACTS_URL
    from app.utils.constants import INSTRUMENT_COLUMN
    from app.utils.constants import REDIS_DATE_FORMAT

    test_config = get_config(ConfigFile.TEST)
    _test_async_redis_client = aioredis.Redis(
        host=test_config.data[TRADES_AND_OPTION_CHAIN_REDIS]["host"],
        port=test_config.data[TRADES_AND_OPTION_CHAIN_REDIS]["port"],
        password=test_config.data[TRADES_AND_OPTION_CHAIN_REDIS]["password"],
        encoding="utf-8",
        decode_responses=True,
        ssl=True,
        ssl_cert_reqs=None,
    )
    await _test_async_redis_client.dbsize()
    await _test_async_redis_client.flushdb()

    # update redis with necessary data i.e expiry list, option chain etc
    expiry_dict = await get_expiry_dict_from_alice_blue()
    for instrument_type, expiry in expiry_dict.items():
        await _test_async_redis_client.set(instrument_type, json.dumps(expiry))

    logging.info(f"Updated redis with expiry list: {datetime.now()}")
    todays_date = datetime.now().date()

    symbols = ["BANKNIFTY", "NIFTY"]
    keys = []
    current_expiry_date, next_expiry_date, is_today_expiry = None, None, False
    for symbol in symbols:
        for index, expiry_date_str in enumerate(expiry_dict[InstrumentTypeEnum.OPTIDX][symbol]):
            expiry_date = datetime.strptime(expiry_date_str, REDIS_DATE_FORMAT).date()
            if todays_date > expiry_date:
                continue
            elif expiry_date == todays_date:
                next_expiry_date = expiry_dict[InstrumentTypeEnum.OPTIDX][symbol][index + 1]
                current_expiry_date = expiry_date_str
                is_today_expiry = True
                break
            elif todays_date < expiry_date:
                current_expiry_date = expiry_date_str
                break

        keys.extend(
            [
                f"{symbol} {current_expiry_date} CE",
                f"{symbol} {current_expiry_date} PE",
            ]
        )
        if is_today_expiry:
            keys.extend(
                [
                    f"{symbol} {next_expiry_date} CE",
                    f"{symbol} {next_expiry_date} PE",
                ]
            )

        (
            current_month_expiry,
            next_month_expiry,
            is_today_months_expiry,
        ) = await get_monthly_expiry_date_from_redis(
            async_redis_client=_test_async_redis_client,
            instrument_type=InstrumentTypeEnum.FUTIDX,
            symbol=symbol,
        )

        keys.append(f"{symbol} {current_month_expiry} FUT")
        if is_today_months_expiry:
            keys.append(f"{symbol} {next_month_expiry} FUT")

    start_time = datetime.now()
    logging.info("start updating redis with option_chain")

    prod_config = get_config()
    prod_async_redis_client = await aioredis.StrictRedis.from_url(
        prod_config.data[TRADES_AND_OPTION_CHAIN_REDIS]["url"],
        encoding="utf-8",
        decode_responses=True,
    )

    all_option_chain = {}
    # Queue up hgetall commands
    async with prod_async_redis_client.pipeline() as pipe:
        for key in keys:
            pipe.hgetall(key)
            option_chain = await pipe.execute()
            # Process results
            all_option_chain[key] = option_chain

    logging.info(f"Pulled option chain from prod redis in [ {datetime.now() - start_time} ]")

    start_time = datetime.now()
    # Queue up hset commands
    async with _test_async_redis_client.pipeline() as pipe:
        for key, option_chain in all_option_chain.items():
            if "FUT" in key:
                # For future option chain first and second argument are same
                pipe.delete(key)
                pipe.hset(key, "FUT", option_chain[0].get("FUT", 0.0))
            else:
                for strike, premium in option_chain[0].items():
                    pipe.hset(key, strike, premium)
        await pipe.execute()

    logging.info(
        f"Time taken to update redis with option chain: [ {datetime.now() - start_time} ]"
    )

    # set up contract in redis
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(AB_NFO_CONTRACTS_URL)

    data_stream = io.StringIO(response.text)
    try:
        df = pd.read_csv(data_stream)
        full_name_row_dict = {}
        for key, value in df.set_index(INSTRUMENT_COLUMN).T.to_dict().items():
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
            pipe.mset(chunk)
        await pipe.execute()

    await push_angel_one_instruments(_test_async_redis_client, symbols=symbols)
    logging.info(f"Time taken to set master contract in redis: [ {datetime.now() - start_time} ]")


@pytest.fixture(scope="session", autouse=True)
def event_loop(request):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_config():
    config = get_config(ConfigFile.TEST)
    return config


@pytest_asyncio.fixture(scope="function", autouse=True)
async def test_async_redis_client():
    test_config = get_config(ConfigFile.TEST)
    _test_async_redis_client = aioredis.Redis(
        host=test_config.data[TRADES_AND_OPTION_CHAIN_REDIS]["host"],
        port=test_config.data[TRADES_AND_OPTION_CHAIN_REDIS]["port"],
        password=test_config.data[TRADES_AND_OPTION_CHAIN_REDIS]["password"],
        encoding="utf-8",
        decode_responses=True,
        ssl=True,
        ssl_cert_reqs=None,
    )

    logging.info("test redis client created")
    # Check Redis connection
    ping = await _test_async_redis_client.ping()
    if ping:
        logging.info("test redis client successfully connected")
    else:
        logging.error("test redis client connection failed")

    broker_pyd_model = BrokerPydanticModel(
        id=test_config.data[ANGELONE_BROKER]["id"],
        name=BrokerNameEnum.ANGELONE,
        username=test_config.data[ANGELONE_BROKER]["username"],
        password=test_config.data[ANGELONE_BROKER]["password"],
        totp=test_config.data[ANGELONE_BROKER]["totp"],
        api_key=test_config.data[ANGELONE_BROKER]["api_key"],
    )
    await _test_async_redis_client.set(
        str(broker_pyd_model.id), broker_pyd_model.model_dump_json()
    )
    yield _test_async_redis_client
    await _test_async_redis_client.close()
    logging.info("test redis client closed")


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
        logging.info("tables dropped")


@pytest.fixture(autouse=True)
async def initialize_db_session(test_config):
    async_db_url = get_db_url(test_config)
    Database.init(async_db_url, engine_kw=engine_kw)

    """session fixture"""
    async with Database() as session:
        logging.info("test db session created")
        yield session
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
async def buy_task_payload_dict(test_async_redis_client: aioredis.Redis):
    post_trade_payload = get_test_post_trade_payload()

    await create_close_trades(users=1, strategies=1, trades=10)
    # query database for stragey

    async with Database() as async_session:
        fetch_strategy_query_ = await async_session.execute(select(StrategyDBModel))
        strategy_db_model = fetch_strategy_query_.scalars().one_or_none()
        strategy_pyd_model = StrategyPydanticModel.model_validate(strategy_db_model)
        (
            current_expiry_date,
            next_expiry_date,
            is_today_expiry,
        ) = await get_current_and_next_expiry_from_redis(
            async_redis_client=test_async_redis_client,
            instrument_type=strategy_pyd_model.instrument_type,
            symbol=strategy_pyd_model.symbol,
        )

        post_trade_payload["strategy_id"] = strategy_db_model.id
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
#     await create_open_trades(test_async_redis_client=test_async_redis_client,async_session=test_async_session, trades=10, ce_trade=True)
#     fetch_trades_query_ = await test_async_session.execute(select(TradeModel))
#     trade_db_models = fetch_trades_query_.scalars().all()
#     mock_redis = MagicMock()
#     mock_redis.exists = AsyncMock(return_value=True)
#     mock_redis.lrange = AsyncMock(
#         return_value=[
#             RedisTradeSchema.model_validate(trade_db_model).json() for trade_db_model in trade_db_models
#         ]
#     )
#     mock_redis.delete = AsyncMock(return_value=True)
#     mock_redis.lpush = AsyncMock(return_value=True)
#     monkeypatch.setattr("tasks.tasks.async_redis_client", mock_redis)
#     return mock_redis
