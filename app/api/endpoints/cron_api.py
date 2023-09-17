from cron.rollover_to_next_expiry import rollover_to_next_expiry
from cron.update_daily_profit import update_daily_profit
from fastapi import APIRouter


cron_api = APIRouter(
    prefix="/api/cron",
    tags=["daily_profit"],
)


@cron_api.get("/update/daily_profit")
async def cron_update_daily_profit():
    await update_daily_profit()
    return "task update_daily_profit successfully executed"


@cron_api.get("/rollover_to_next_expiry")
async def cron_rollover_to_next_expiry():
    await rollover_to_next_expiry()
    return "task rollover_to_next_expiry successfully executed"
