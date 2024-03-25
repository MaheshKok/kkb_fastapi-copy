import aioredis
from sqlalchemy.engine.url import URL

from app.core.config import Config
from app.utils.constants import TRADES_AND_OPTION_CHAIN_REDIS


engine_kw = {
    # "echo": False,  # print all SQL statements
    "pool_pre_ping": True,
    # feature will normally emit SQL equivalent to “SELECT 1” each time a connection is checked out from the pool
    "pool_size": 2,  # number of connections to keep open at a time
    "max_overflow": 4,  # number of connections to allow to be opened above pool_size
    "connect_args": {
        "prepared_statement_cache_size": 0,  # disable prepared statement cache
        "statement_cache_size": 0,  # disable statement cache
    },
}


def get_db_url(config: Config) -> URL:
    config_db = config.data["db"]
    return URL.create(drivername="postgresql+asyncpg", **config_db)


# Not in use
# def get_async_session_maker(async_db_url: URL) -> sessionmaker:
#     async_engine = create_async_engine(
#         async_db_url,
#         poolclass=QueuePool,
#         pool_recycle=3600,
#         pool_pre_ping=True,
#         pool_size=60,
#         max_overflow=80,
#         pool_timeout=30,
#     )
#     async_session_maker = sessionmaker(
#         bind=async_engine, expire_on_commit=False, class_=AsyncSession
#     )
#     return async_session_maker


def get_redis_client(config: Config) -> aioredis.StrictRedis:
    # Note: we don't need to use create_pool explicitly as celery does it for us
    if config.data["ENVIRONMENT"] == "test":
        return aioredis.Redis(
            host=config.data[TRADES_AND_OPTION_CHAIN_REDIS]["host"],
            port=config.data[TRADES_AND_OPTION_CHAIN_REDIS]["port"],
            password=config.data[TRADES_AND_OPTION_CHAIN_REDIS]["password"],
            encoding="utf-8",
            decode_responses=True,
        )
    return aioredis.StrictRedis.from_url(
        config.data[TRADES_AND_OPTION_CHAIN_REDIS]["url"], encoding="utf-8", decode_responses=True
    )
