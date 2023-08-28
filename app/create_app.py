import asyncio
import logging
import logging.config
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.types import Send

from app.api.endpoints.healthcheck import healthcheck_router
from app.api.endpoints.strategy import strategy_router
from app.api.endpoints.takeaway_profit import takeaway_profit
from app.api.endpoints.trade import options_router
from app.api.endpoints.trade import trading_router
from app.core.config import get_config
from app.database.base import engine_kw
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.database.session_manager.db_session import Database
from app.extensions.redis_cache.on_start import cache_ongoing_trades


logger = logging.getLogger(__name__)


def register_routers(app: FastAPI):
    # include all routers
    app.include_router(healthcheck_router)
    app.include_router(trading_router)
    app.include_router(options_router)
    app.include_router(strategy_router)
    app.include_router(takeaway_profit)


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Send) -> Response:
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        try:
            logger.info(
                f" API: [ {request.scope['route'].path} ] request processing time: {process_time} seconds"
            )
        except KeyError:
            logger.info(f" Invalid Api Endpoint: [ {request.scope['path']} ]")

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
    app.add_middleware(TimingMiddleware)

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
    logger.info("Triggered background tasks to sync redis with database")

    try:
        yield
    finally:
        logging.info("Application shutdown")
        # Close the connection when the application shuts down
        await Database.close()
        await app.state.async_redis_client.close()
        await app.state.async_session_maker.kw["bind"].dispose()
