import logging

from fastapi import FastAPI
from fastapi import Request
from fastapi_sa.database import db
from fastapi_sa.middleware import DBSessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from app.api.endpoints.healthcheck import healthcheck_router
from app.api.endpoints.trading import options_router
from app.core.config import get_config
from app.database.base import lifespan


def register_routers(app: FastAPI):
    # include all routers
    app.include_router(healthcheck_router)
    app.include_router(options_router)
    pass


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
    app.add_middleware(
        DBSessionMiddleware,
    )
    app.add_middleware(ConnectionLoggingMiddleware)

    # Include routers
    register_routers(app)

    # TODO: register scout and new relic

    return app
