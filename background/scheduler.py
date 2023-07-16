import asyncio
import logging
from datetime import datetime

import aiocron
import httpx


logging.basicConfig(level=logging.INFO)

base_urls = {
    "flaskstockpi": "https://flaskstockapi.herokuapp.com/api",
    "kokobrothers-be": "https://kokobrothers-be.herokuapp.com/api",
}


async def get_api(url):
    try:
        logging.info(f"get_api: {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
        logging.info(f"get_api: {response.json()}")
    except Exception as e:
        logging.error(f"get_api: {e}")
        return None


async def task_interval_test():
    logging.info(f"job interval_test executed at: {datetime.now()}")


async def task_cron_test():
    logging.info(f"job cron_test executed at: {datetime.now()}")


async def task_clean_redis():
    logging.info(f"Job task_clean_redis executed at: {datetime.now()}")
    tasks = []
    for app in base_urls:
        if app == "flaskstockpi":
            tasks.append(get_api(f"{base_urls[app]}/clean_redis"))
    await asyncio.gather(*tasks)


async def task_update_expiry_list():
    logging.info(f"Job update_expiry_list executed at: {datetime.now()}")
    tasks = []
    for app in base_urls:
        tasks.append(get_api(f"{base_urls[app]}/update_expiry_list"))
    await asyncio.gather(*tasks)


async def task_update_session_token():
    logging.info(f"Job update_session_token executed at: {datetime.now()}")
    tasks = []
    for app in base_urls:
        if app == "flaskstockpi":
            tasks.append(get_api(f"{base_urls[app]}/update_ablue_session_token"))
    await asyncio.gather(*tasks)


async def task_up_scale_dynos():
    logging.info(f"Job up_scale_dynos executed at: {datetime.now()}")

    action = "upscale"
    dyno_type = "Standard-1x"

    tasks = []
    for app in base_urls:
        if app == "flaskstockpi":
            web = 2
            worker = 2
        else:
            web = 1
            worker = 1

        tasks.append(
            get_api(
                f"{base_urls[app]}/scale_dynos?dyno_type={dyno_type}&qty=1&action={action}&web_quantity={web}&worker_quantity={worker}"
            )
        )

    # wait for all tasks to complete
    await asyncio.gather(*tasks)


async def task_down_scale_dynos():
    logging.info(f"Job down_scale_dynos executed at: {datetime.now()}")
    action = "downscale"
    dyno_type = "Eco"
    web = 1
    worker = 1

    tasks = []
    for app in base_urls:
        tasks.append(
            get_api(
                f"{base_urls[app]}/scale_dynos?dyno_type={dyno_type}&qty=1&action={action}&web_quantity={web}&worker_quantity={worker}"
            )
        )

    # wait for all tasks to complete
    await asyncio.gather(*tasks)


async def task_update_till_yesterdays_profits():
    logging.info(f"Job update_till_yesterdays_profits executed at: {datetime.now()}")
    tasks = []
    for app in base_urls:
        if app == "flaskstockpi":
            tasks.append(get_api(f"{base_urls[app]}/update_till_yesterdays_profits"))

    # wait for all tasks to complete
    await asyncio.gather(*tasks)


async def task_rollover_to_next_expiry():
    logging.info(f"Job task_rollover_to_next_expiry executed at: {datetime.now()}")

    tasks = []
    for app in base_urls:
        if app == "flaskstockpi":
            tasks.append(get_api(f"{base_urls[app]}/rollover_to_next_expiry"))

    # wait for all tasks to complete
    await asyncio.gather(*tasks)


async def task_backup_db():
    logging.info(f"Job task_backup_db executed at: {datetime.now()}")

    tasks = []
    for app in base_urls:
        if app == "flaskstockpi":
            tasks.append(get_api(f"{base_urls[app]}/start_backup"))

    # wait for all tasks to complete
    await asyncio.gather(*tasks)


aiocron.crontab("*/60 * * * *", func=task_interval_test)  # Every 60 minutes
aiocron.crontab("20 23 * * *", func=task_cron_test)  # At 23:19 every day
aiocron.crontab("0 2 * * *", func=task_backup_db)  # Every day at 02:00
aiocron.crontab("0 3 * * 5", func=task_clean_redis)  # Every Friday at 03:00
aiocron.crontab("0 3 * * *", func=task_update_expiry_list)  # Every day at 03:00
aiocron.crontab("10 3 * * *", func=task_update_session_token)  # Every day at 03:10
aiocron.crontab("30 3 * * *", func=task_update_session_token)  # Every day at 03:30
aiocron.crontab("30 3 * * *", func=task_up_scale_dynos)  # Every day at 03:30
aiocron.crontab("30 9 * * *", func=task_rollover_to_next_expiry)  # Every day at 9:30
aiocron.crontab("0 10 * * *", func=task_down_scale_dynos)  # Every day at 10:00
aiocron.crontab("5 10 * * *", func=task_update_till_yesterdays_profits)  # Every day at 10:05


# Run the main loop
loop = asyncio.get_event_loop()
try:
    loop.run_forever()
except KeyboardInterrupt:
    pass
finally:
    loop.close()
