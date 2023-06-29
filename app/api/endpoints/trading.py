import json
import logging
from datetime import datetime

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends
from httpx import AsyncClient
from pydantic import parse_obj_as
from tasks.execution import task_entry_trade
from tasks.execution import task_exit_trade

from app.api.dependency import get_async_httpx_client
from app.api.dependency import get_async_redis_client
from app.api.dependency import get_strategy_schema
from app.api.utils import get_current_and_next_expiry
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema


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
    signal_payload_schema: SignalPayloadSchema,
    strategy_schema: StrategySchema = Depends(get_strategy_schema),
    async_redis_client: Redis = Depends(get_async_redis_client),
    async_httpx_client: AsyncClient = Depends(get_async_httpx_client),
):
    todays_date = datetime.now().date()
    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        async_redis_client, todays_date
    )

    exiting_trades_key = f"{signal_payload_schema.strategy_id} {current_expiry_date} {'PE' if signal_payload_schema.option_type == 'CE' else 'CE' }"

    # TODO: in future decide based on strategy new column, strategy_type:
    # if strategy_position is "every" then close all ongoing trades and buy new trade
    # 2. strategy_position is "signal", then on action: EXIT, close same option type trades
    # and buy new trade on BUY action,
    # To be decided in future, the name of actions

    signal_payload_schema.expiry = current_expiry_date
    try:
        if exiting_trades_list_json := await async_redis_client.lrange(exiting_trades_key, 0, -1):
            # initiate celery close_trade
            logging.info(f"Total: {len(exiting_trades_list_json)} trades to be closed")
            redis_trade_schema_list = parse_obj_as(
                list[RedisTradeSchema], [json.loads(trade) for trade in exiting_trades_list_json]
            )
            await task_exit_trade(
                signal_payload_schema,
                exiting_trades_key,
                redis_trade_schema_list,
                async_redis_client,
                strategy_schema,
                async_httpx_client,
            )
    except Exception as e:
        logging.error(f"Exception while exiting trade: {e}")

    # initiate celery buy_trade
    return await task_entry_trade(
        signal_payload_schema, async_redis_client, strategy_schema, async_httpx_client
    )
