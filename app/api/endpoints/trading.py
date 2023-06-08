from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends

from app.api.dependency import get_redis_pool
from app.api.dependency import is_valid_strategy
from app.database.models import Strategy
from app.schemas.trade import TradePostSchema
from app.schemas.trade import TradeSchema


trading_router = APIRouter(
    prefix="/api/trading",
    tags=["trading"],
)


@trading_router.post("/nfo", status_code=201, response_model=TradeSchema)
async def post_nfo(
    payload: TradePostSchema,
    strategy_db: Strategy = Depends(is_valid_strategy),
    redis: Redis = Depends(get_redis_pool),
):
    result = eval(await redis.get("expiry_list"))
    print(result)
    print(payload)
    print(strategy_db)
