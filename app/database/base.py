from gino import Gino
from sqlalchemy.engine.url import URL

from app.core.config import Config

db = Gino()


async def get_db_url(config: Config) -> URL:
    config_db = config.data["db"]
    return URL(drivername="postgresql+asyncpg", **config_db)


async def setup_and_teardown_db(app):
    @app.on_event("startup")
    async def startup():
        db_url = await get_db_url(app.state.config)
        await db.set_bind(db_url)

    @app.on_event("shutdown")
    async def shutdown_event():
        await db.pop_bind().close()
