from gino import Gino
from sqlalchemy.engine.url import URL

from app.core.config import Config

db: Gino = Gino()


def get_db_url(config: Config, drivername="postgresql+asyncpg") -> URL:
    config_db = config.data["db"]
    return URL(drivername=drivername, **config_db)


async def setup_and_teardown_db(app):
    @app.on_event("startup")
    async def startup():
        db_url = get_db_url(app.state.config)
        await db.set_bind(db_url)

    @app.on_event("shutdown")
    async def shutdown_event():
        await db.pop_bind().close()
