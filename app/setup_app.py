from fastapi import FastAPI

from app.api.endpoints.healthcheck import healthcheck_router
from app.core.config import get_config
from app.database.base import lifespan


def register_routers(app):
    from app.api.endpoints.trading import trading_router

    # include all routers
    app.include_router(healthcheck_router)
    app.include_router(trading_router)
    pass


def get_application(config_file) -> FastAPI:
    config = get_config(config_file)
    app = FastAPI(
        title="Trading System API", debug=True, lifespan=lifespan
    )  # change debug based on environment
    app.state.config = config

    # Add middleware, event handlers, etc. here

    # Include routers
    register_routers(app)

    # TODO: register scout and new relic
    # await app_lifespan(app)

    return app
