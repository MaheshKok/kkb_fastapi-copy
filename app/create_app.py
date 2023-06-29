import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from fastapi_sa.database import db
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from app.api.endpoints.healthcheck import healthcheck_router
from app.api.endpoints.strategy import strategy_router
from app.api.endpoints.trading import options_router
from app.core.config import get_config
from app.database.base import engine_kw
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.extensions.redis_cache.on_start import cache_ongoing_trades


def register_routers(app: FastAPI):
    # include all routers
    app.include_router(healthcheck_router)
    app.include_router(options_router)
    app.include_router(strategy_router)


def get_num_connections():
    return db.engine.pool.status()


class ConnectionLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # Get the number of connections before the request
        num_connections_before = get_num_connections()  # replace with actual method

        response = await call_next(request)

        # Get the number of connections after the request
        num_connections_after = get_num_connections()  # replace with actual method

        logging.info(f"Connections before request: {num_connections_before}")
        logging.info(f"Connections after request: {num_connections_after}")

        return response


def get_app(config_file) -> FastAPI:
    config = get_config(config_file)
    app = FastAPI(
        title="Trading System API", debug=True, lifespan=lifespan
    )  # change debug based on environment
    app.state.config = config
    # Add middleware, event handlers, etc. here
    # app.add_middleware(DBSessionMiddleware)
    # Include routers
    register_routers(app)

    # TODO: register scout and new relic

    return app


# TODO: if you want lifespan to work then consider moving it to another file
@asynccontextmanager
async def lifespan(app):
    logging.info("Application startup")
    async_db_url = get_db_url(app.state.config)

    db.init(async_db_url, engine_kw=engine_kw)
    logging.info("Initialized database")
    async_redis_client = get_redis_client(app.state.config)
    logging.info("Initialized redis")
    app.state.async_redis_client = async_redis_client

    # create a task to cache ongoing trades in Redis
    asyncio.create_task(cache_ongoing_trades(async_redis_client))

    try:
        yield
    finally:
        logging.info("Application shutdown")
        # Close the connection when the application shuts down
        await db.close()
        await app.state.async_redis_client.close()
        await app.state.async_session_maker.kw["bind"].dispose()
