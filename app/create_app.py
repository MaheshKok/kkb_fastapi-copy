import asyncio
import logging
from contextlib import asynccontextmanager

import sentry_sdk
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from cron.download_master_contracts import download_master_contract
from cron.scheduler import task_backup_db
from cron.scheduler import task_clean_redis
from cron.scheduler import task_cron_test
from cron.scheduler import task_interval_test
from cron.scheduler import task_rollover_long_options_to_next_expiry
from cron.scheduler import task_rollover_short_options_and_futures_to_next_expiry
from cron.scheduler import task_update_daily_profit
from cron.scheduler import task_update_expiry_list
from cron.scheduler import task_update_session_token
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.healthcheck import healthcheck_router
from app.api.strategy import strategy_router
from app.api.trade import trading_router
from app.api.trade.binance.crypto import binance_router
from app.api.trade.capital.router import forex_router
from app.api.trade.indian_fno.alice_blue.router import fno_router
from app.api.trade.indian_fno.angel_one.router import angel_one_router
from app.api.trade.oanda.router import oanda_forex_router
from app.core.config import get_config
from app.database.base import engine_kw
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.database.session_manager.db_session import Database
from app.extensions.redis_cache.on_start import cache_ongoing_trades
from app.utils.constants import ConfigFile


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


def register_routers(app: FastAPI):
    # include all routers
    app.include_router(healthcheck_router)
    app.include_router(trading_router)
    app.include_router(fno_router)
    app.include_router(angel_one_router)
    app.include_router(strategy_router)
    app.include_router(forex_router)
    app.include_router(binance_router)
    app.include_router(oanda_forex_router)


def register_sentry():
    sentry_sdk.init(
        dsn="https://ce37badd7d894b97a19dc645745e0730@o1202314.ingest.sentry.io/6327385",
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=1.0,
        environment="kokobrothers-fastapi-864126af779b",
    )


def register_cron_jobs(scheduler: AsyncIOScheduler):
    logging.info("Scheduling cron jobs")
    # Schedule your cron jobs here
    scheduler.add_job(task_interval_test, IntervalTrigger(hours=1))  # Every 60 minutes
    scheduler.add_job(
        task_cron_test, CronTrigger.from_crontab("20 23 * * *")
    )  # At 23:20 every day
    scheduler.add_job(task_backup_db, CronTrigger.from_crontab("0 2 * * *"))  # Every day at 02:00
    scheduler.add_job(
        task_clean_redis, CronTrigger.from_crontab("0 1 * * 5")
    )  # Every Friday at 03:00
    scheduler.add_job(
        download_master_contract, CronTrigger.from_crontab("45 2 * * *")
    )  # Every day at 02:45
    scheduler.add_job(
        task_update_expiry_list, CronTrigger.from_crontab("0 3 * * *")
    )  # Every day at 03:00
    scheduler.add_job(
        task_update_session_token, CronTrigger.from_crontab("10 3 * * *")
    )  # Every day at 03:10
    scheduler.add_job(
        task_update_session_token, CronTrigger.from_crontab("30 3 * * *")
    )  # Every day at 03:30
    scheduler.add_job(
        task_rollover_long_options_to_next_expiry, CronTrigger.from_crontab("30 8 * * *")
    )  # Every day at 8:30
    scheduler.add_job(
        task_rollover_short_options_and_futures_to_next_expiry,
        CronTrigger.from_crontab("45 9 * * *"),
    )  # Every day at 9:45
    scheduler.add_job(
        task_update_daily_profit, CronTrigger.from_crontab("5 10 * * *")
    )  # Every day at 10:05


def start_schedular():
    # Initialize and start the scheduler
    scheduler = AsyncIOScheduler()
    register_cron_jobs(scheduler)
    scheduler.start()


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

    # For Some reason, heroku doesn't support APScheduler, investigate why
    if config_file != ConfigFile.TEST:
        start_schedular()

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
