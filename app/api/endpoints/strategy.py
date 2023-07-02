import logging

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends

from app.api.dependency import get_async_redis_client
from app.database.models import StrategyModel
from app.database.sqlalchemy_client.client import Database
from app.schemas.strategy import StrategyCreateSchema
from app.schemas.strategy import StrategySchema


strategy_router = APIRouter(
    prefix="/api/strategy",
    tags=["strategy"],
)


@strategy_router.post("", response_model=StrategySchema)
async def post_strategy(
    strategy_schema: StrategyCreateSchema,
    async_redis_client: Redis = Depends(get_async_redis_client),
):
    async with Database() as async_session:
        strategy_model = StrategyModel(**strategy_schema.dict())
        async_session.add(strategy_model)
        await async_session.flush()
        await async_session.refresh(strategy_model)

        redis_set_result = await async_redis_client.set(
            str(strategy_model.id), StrategySchema.from_orm(strategy_model).json()
        )
        if not redis_set_result:
            raise Exception(f"Redis set strategy: {strategy_model.id} failed")

        logging.info(f"{strategy_model.id} added to redis")

        return strategy_model
