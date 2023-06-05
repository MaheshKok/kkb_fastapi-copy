from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.config import Config


Base = declarative_base()


def get_db_url(config: Config) -> URL:
    config_db = config.data["db"]
    return URL.create(drivername="postgresql+asyncpg", **config_db)


def create_async_session_maker(async_db_url: URL) -> sessionmaker:
    async_engine = create_async_engine(async_db_url)
    async_session_maker = sessionmaker(
        bind=async_engine, expire_on_commit=False, class_=AsyncSession
    )
    return async_session_maker


async def setup_and_teardown_db(app):
    @app.on_event("startup")
    async def startup():
        async_db_url = get_db_url(app.state.config)
        app.state.async_session_maker = create_async_session_maker(async_db_url)

    @app.on_event("shutdown")
    async def shutdown_event():
        await app.state.async_session_maker.kw["bind"].close()
