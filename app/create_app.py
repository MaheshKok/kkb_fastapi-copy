import asyncio
import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.endpoints.cron_api import cron_api
from app.api.endpoints.healthcheck import healthcheck_router
from app.api.endpoints.strategy import strategy_router
from app.api.endpoints.takeaway_profit import takeaway_profit
from app.api.endpoints.trade import trading_router
from app.api.endpoints.trade.cfd import forex_router
from app.api.endpoints.trade.crypto import binance_router
from app.api.endpoints.trade.indian_futures_and_options import fno_router
from app.core.config import get_config
from app.database.base import engine_kw
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.database.session_manager.db_session import Database
from app.extensions.redis_cache.on_start import cache_ongoing_trades


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


def register_routers(app: FastAPI):
    # include all routers
    app.include_router(healthcheck_router)
    app.include_router(trading_router)
    app.include_router(fno_router)
    app.include_router(strategy_router)
    app.include_router(takeaway_profit)
    app.include_router(forex_router)
    app.include_router(binance_router)
    app.include_router(cron_api)


def register_sentry():
    sentry_sdk.init(
        dsn="https://ce37badd7d894b97a19dc645745e0730@o1202314.ingest.sentry.io/6327385",
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=1.0,
        environment="kokobrothers-fastapi-864126af779b",
    )


def get_app(config_file) -> FastAPI:
    config = get_config(config_file)
    app = FastAPI(
        title="Trading System API", lifespan=lifespan
    )  # change debug based on environment
    app.state.config = config
    # Add middleware, event handlers, etc. here
    # app.add_middleware(DBSessionMiddleware)
    # Include routers
    register_routers(app)

    # Set up CORS middleware
    origins = [
        "http://localhost:3000",  # For local development
        "https://kokobrothers.herokuapp.com",
        # Add any other origins as needed
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # TODO: register scout and new relic

    return app


# TODO: if you want lifespan to work then consider moving it to another file
@asynccontextmanager
async def lifespan(app):
    logging.info("Application startup")
    async_db_url = get_db_url(app.state.config)

    Database.init(async_db_url, engine_kw=engine_kw)
    logging.info("Initialized database")
    async_redis_client = get_redis_client(app.state.config)
    logging.info("Initialized redis")
    app.state.async_redis_client = async_redis_client

    # create a task to cache ongoing trades in Redis
    asyncio.create_task(cache_ongoing_trades(async_redis_client))
    logging.info("Triggered background tasks to sync redis with database")

    try:
        yield
    finally:
        logging.info("Application shutdown")
        # Close the connection when the application shuts down
        await app.state.async_redis_client.close()
        await app.state.async_session_maker.kw["bind"].dispose()
