import json
import logging
from datetime import datetime

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends
from tasks.tasks import task_buying_trade
from tasks.tasks import task_exiting_trades

from app.api.dependency import get_async_redis
from app.api.dependency import is_valid_strategy
from app.api.utils import get_current_and_next_expiry
from app.database.models import StrategyModel
from app.schemas.trade import CeleryTradeSchema
from app.schemas.trade import EntryTradeSchema
from app.utils.constants import ConfigFile


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    trade_post_schema: EntryTradeSchema,
    strategy: StrategyModel = Depends(is_valid_strategy),
    async_redis: Redis = Depends(get_async_redis),
):
    todays_date = datetime.now().date()
    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        async_redis, todays_date
    )

    exiting_trades_key = f"{trade_post_schema.strategy_id} {current_expiry_date} {'PE' if trade_post_schema.option_type == 'CE' else 'CE' }"

    # TODO: in future decide based on strategy new column, strategy_type:
    # if strategy_position is "every" then close all ongoing trades and buy new trade
    # 2. strategy_position is "signal", then on action: EXIT, close same option type trades
    # and buy new trade on BUY action,
    # To be decided in future, the name of actions

    celery_trade_payload_json = CeleryTradeSchema(
        **trade_post_schema.dict(), symbol=strategy.symbol, expiry=current_expiry_date
    ).json()

    try:
        if exiting_trades := await async_redis.lrange(exiting_trades_key, 0, -1):
            exiting_trades_json = json.dumps(exiting_trades)
            # initiate celery close_trade
            print(f"found: {len(exiting_trades)} trades to be closed")
            task_exiting_trades.delay(
                celery_trade_payload_json,
                exiting_trades_key,
                exiting_trades_json,
                ConfigFile.PRODUCTION,
            )
    except Exception as e:
        logging.info(f"Exception: {e}")

    # initiate celery buy_trade

    task_buying_trade.delay(
        celery_trade_payload_json,
        ConfigFile.PRODUCTION,
    )

    return {"message": "Trade initiated successfully"}
