import asyncio
import ssl

from celery import Celery
from tasks.execution import execute_celery_buy_trade_task
from tasks.execution import execute_celery_exit_trade_task

from app.core.config import get_config


config = get_config()
redis_url = config.data["celery_redis"]["url"]

celery = Celery(
    "KokoBrothersBackend",
    broker=redis_url,
    backend=redis_url,
    broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    include=["tasks.tasks"],
    broker_connection_retry_on_startup=True,
)


@celery.task(name="tasks.exiting_trades")
def task_exiting_trades(payload_json, redis_ongoing_key, exiting_trades_json, config_file):
    # Create a new event loop
    loop = asyncio.new_event_loop()

    # Set the event loop as the default for the current context
    asyncio.set_event_loop(loop)

    # Use the event loop to run the asynchronous function
    result = loop.run_until_complete(
        execute_celery_exit_trade_task(
            payload_json, redis_ongoing_key, exiting_trades_json, config_file
        )
    )

    # Return the result
    return result


@celery.task(name="tasks.buying_trade")
def task_buying_trade(payload_json, config_file):
    # Create a new event loop
    loop = asyncio.new_event_loop()

    # Set the event loop as the default for the current context
    asyncio.set_event_loop(loop)

    # Use the event loop to run the asynchronous function
    result = loop.run_until_complete(execute_celery_buy_trade_task(payload_json, config_file))

    # Return the result
    return result
