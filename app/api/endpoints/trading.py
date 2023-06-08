from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends

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
    payload: TradePostSchema,
    strategy_db: Strategy = Depends(is_valid_strategy),
    redis: Redis = Depends(get_redis_pool),
):
    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry()

    opposite_option_type_ongoing_trades_key = (
        f"{payload.strategy_id} {current_expiry_date} {get_opposite_option_type(payload.action)}"
    )

    # TODO: in future decide based on strtegy new column, strategy_type:
    # if strategy_position is "every" then close all ongoing trades and buy new trade
    # 2. strategy_position is "signal", then on EXIT action close same option type trades
    # and buy new trade on BUY action, to be decided in future

    if ongoing_trades := await redis.get(opposite_option_type_ongoing_trades_key):
        # initiate celery close_trade
        print(f"found trades to be {len(ongoing_trades)}")
        pass

    # initiate celery buy_trade
    pass
