from fastapi import FastAPI

from app.api.endpoints.healthcheck import healthcheck_router
from app.api.endpoints.trading import trading_router
from app.core.config import Config
from app.database.base import lifespan


async def register_routers(app):
    # include all routers
    app.include_router(healthcheck_router)
    app.include_router(trading_router)
    pass


async def get_application(config: Config) -> FastAPI:
    app = FastAPI(
        title="Trading System API", debug=True, lifespan=lifespan
    )  # change debug based on environment
    app.state.config = config
    # Add middleware, event handlers, etc. here

    # Include routers
    await register_routers(app)

    # TODO: register scout and new relic
    # await app_lifespan(app)

    return app
