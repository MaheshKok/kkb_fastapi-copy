import asyncio
import ssl

from celery import Celery
from celery.signals import worker_process_init
from tasks.execution import task_entry_trade
from tasks.execution import task_exit_trade

from app.core.config import get_config


config = get_config()
redis_url = config.data["celery_redis"]["url"]

celery_app = Celery(
    "KokoBrothersBackend",
    broker=redis_url,
    backend=redis_url,
    broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    include=["tasks.tasks"],
    broker_connection_retry_on_startup=True,
)


# Define the worker_process_init signal handler
@worker_process_init.connect
def on_worker_init(**kwargs):
    # Connect to the database using connect_to_db
    # init_db(ConfigFile.PRODUCTION)
    pass


@celery_app.task(name="tasks.exiting_trades")
def task_exiting_trades(payload_json, redis_ongoing_key, exiting_trades_json, config_file):
    # Create a new event loop
    loop = asyncio.new_event_loop()

    # Set the event loop as the default for the current context
    asyncio.set_event_loop(loop)

    # Use the event loop to run the asynchronous function
    result = loop.run_until_complete(
        task_exit_trade(payload_json, redis_ongoing_key, exiting_trades_json, config_file)
    )

    # Return the result
    return result


@celery_app.task(name="tasks.buying_trade")
def task_buying_trade(payload_json, config_file):
    # Create a new event loop
    loop = asyncio.new_event_loop()

    # Set the event loop as the default for the current context
    asyncio.set_event_loop(loop)

    # Use the event loop to run the asynchronous function
    result = loop.run_until_complete(task_entry_trade(payload_json, config_file))

    # Return the result
    return result
