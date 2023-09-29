import logging

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy import select

from app.api.dependency import get_async_redis_client
from app.database.models import StrategyModel
from app.database.session_manager.db_session import Database
from app.schemas.strategy import StrategyCreateSchema
from app.schemas.strategy import StrategySchema


strategy_router = APIRouter(
    prefix="/api/strategy",
    tags=["strategy"],
)


@strategy_router.get("", response_model=list[StrategySchema])
async def get_strategies():
    async with Database() as async_session:
        fetch_strategy_query = await async_session.execute(select(StrategyModel))
        strategy_models = fetch_strategy_query.scalars().all()
        return strategy_models


@strategy_router.post("", response_model=StrategySchema)
async def post_strategy(
    strategy_schema: StrategyCreateSchema,
    async_redis_client: Redis = Depends(get_async_redis_client),
):
    async with Database() as async_session:
        strategy_model = StrategyModel(**strategy_schema.model_dump())
        async_session.add(strategy_model)
        await async_session.flush()
        await async_session.refresh(strategy_model)

        redis_set_result = await async_redis_client.hset(
            str(strategy_model.id),
            "strategy",
            StrategySchema.model_validate(strategy_model).model_dump_json(),
        )
        if not redis_set_result:
            raise Exception(f"Redis set strategy: {strategy_model.id} failed")

        logging.info(f"{strategy_model.id} added to redis")

        return strategy_model
