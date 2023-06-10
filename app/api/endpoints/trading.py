from datetime import datetime

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from tasks.tasks import task_buying_trade

from app.api.dependency import get_redis_pool
from app.api.dependency import is_valid_strategy
from app.api.utils import get_current_and_next_expiry
from app.api.utils import get_opposite_option_type
from app.database.models import Strategy
from app.schemas.trade import TradePostSchema


trading_router = APIRouter(
    prefix="/api/trading",
    tags=["trading"],
)


@trading_router.post("/nfo", status_code=200)
async def post_nfo(
    request: Request,
    trade: TradePostSchema,
    strategy: Strategy = Depends(is_valid_strategy),
    redis: Redis = Depends(get_redis_pool),
):
    payload = await request.json()
    payload["option_type"] = trade.option_type
    payload["symbol"] = strategy.symbol

    todays_date = datetime.now().date()
    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        todays_date
    )

    opposite_option_type_ongoing_trades_key = (
        f"{trade.strategy_id} {current_expiry_date} {get_opposite_option_type(trade.action)}"
    )

    # TODO: in future decide based on strategy new column, strategy_type:
    # if strategy_position is "every" then close all ongoing trades and buy new trade
    # 2. strategy_position is "signal", then on action: EXIT, close same option type trades
    # and buy new trade on BUY action,
    # To be decided in future, what actions would be

    if ongoing_trades := await redis.get(opposite_option_type_ongoing_trades_key):
        # initiate celery close_trade
        print(f"found: {len(ongoing_trades)} trades to be closed")
        pass

    # initiate celery buy_trade
    task_buying_trade.delay(payload, str(current_expiry_date))
