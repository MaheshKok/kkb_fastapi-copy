from cron.update_daily_profit import update_daily_profit
from fastapi import APIRouter


takeaway_profit = APIRouter(
    prefix="/api/update/daily_profit",
    tags=["daily_profit"],
)


# api endpoint type doesnt correlate to the actual functionality
@takeaway_profit.get("")
async def _update_daily_profit():
    await update_daily_profit()
    return "task successfully executed"
