from fastapi import FastAPI
from fastapi_sa.middleware import DBSessionMiddleware

from app.api.endpoints.healthcheck import healthcheck_router
from app.api.endpoints.trading import options_router
from app.core.config import get_config
from app.database.base import lifespan


def register_routers(app: FastAPI):
    # include all routers
    app.include_router(healthcheck_router)
    app.include_router(options_router)
    pass


def get_app(config_file) -> FastAPI:
    config = get_config(config_file)
    app = FastAPI(
        title="Trading System API", debug=True, lifespan=lifespan
    )  # change debug based on environment
    app.state.config = config
    app.add_middleware(
        DBSessionMiddleware,
    )

    # Add middleware, event handlers, etc. here

    # Include routers
    register_routers(app)

    # TODO: register scout and new relic

    return app
