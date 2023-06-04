from fastapi import FastAPI

from app.api.endpoints.trading import healthcheck_router
from app.core.config import Config
from app.database.base import setup_and_teardown_db


async def register_routers(app):
    # include all routers
    app.include_router(healthcheck_router)
    pass


async def get_application(config: Config) -> FastAPI:
    app = FastAPI(title="Trading System API", debug=True)  # change debug based on environment
    app.state.config = config
    # Add middleware, event handlers, etc. here

    # Include routers
    await register_routers(app)
    await setup_and_teardown_db(app)

    return app
