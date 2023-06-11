from datetime import datetime

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from tasks.tasks import task_buying_trade

from app.api.dependency import get_redis_pool
from app.api.dependency import is_valid_strategy
from app.api.utils import get_current_and_next_expiry
from app.database.models import StrategyModel
from app.schemas.trade import TradePostSchema


trading_router = APIRouter(
    prefix="/api/trading",
    tags=["trading"],
)


options_router = APIRouter(
    prefix=f"{trading_router.prefix}/nfo",
    tags=["options"],
)

futures_router = APIRouter(
    prefix=f"{trading_router.prefix}/nfo",
    tags=["futures"],
)


@options_router.post("/options", status_code=200)
async def post_nfo(
    request: Request,
    trade_post_schema: TradePostSchema,
    strategy: StrategyModel = Depends(is_valid_strategy),
    redis: Redis = Depends(get_redis_pool),
):
    payload = await request.json()

    todays_date = datetime.now().date()
    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        todays_date
    )

    payload["option_type"] = trade_post_schema.option_type
    payload["symbol"] = strategy.symbol
    payload["expiry"] = str(current_expiry_date)

    opposite_option_type_ongoing_trades_key = f"{trade_post_schema.strategy_id} {current_expiry_date} {'PE' if trade_post_schema.option_type == 'CE' else 'CE' }"

    # TODO: in future decide based on strategy new column, strategy_type:
    # if strategy_position is "every" then close all ongoing trades and buy new trade
    # 2. strategy_position is "signal", then on action: EXIT, close same option type trades
    # and buy new trade on BUY action,
    # To be decided in future, the name of actions

    if opposite_option_type_ongoing_trades := await redis.get(
        opposite_option_type_ongoing_trades_key
    ):
        # initiate celery close_trade
        print(f"found: {len(opposite_option_type_ongoing_trades)} trades to be closed")
        pass

    # initiate celery buy_trade
    task_buying_trade.delay(payload)
    return {"message": "Trade initiated successfully"}
