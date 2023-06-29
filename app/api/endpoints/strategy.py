import logging

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends
from fastapi_sa.database import db

from app.api.dependency import get_async_redis_client
from app.database.models import StrategyModel
from app.schemas.strategy import StrategyCreateSchema
from app.schemas.strategy import StrategySchema


strategy_router = APIRouter(
    prefix="/api/strategy",
    tags=["strategy"],
)


@strategy_router.post("")
async def post_strategy(
    strategy_schema: StrategyCreateSchema,
    async_redis_client: Redis = Depends(get_async_redis_client),
):
    strategy_model = StrategyModel(**strategy_schema.dict())
    db.session.add(strategy_model)
    await db.session.flush()
    await db.session.refresh(strategy_model)

    redis_set_result = await async_redis_client.set(
        str(strategy_model.id), StrategySchema.from_orm(strategy_model).json()
    )
    if not redis_set_result:
        raise Exception(f"Redis set strategy: {strategy_model.id} failed")

    logging.info(f"{strategy_model.id} added to redis")

    return strategy_model
