import logging

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy import select

from app.api.dependency import get_async_redis_client
from app.database.models import StrategyModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.strategy import StrategyCreatePydanticModel
from app.pydantic_models.strategy import StrategyPydanticModel


strategy_router = APIRouter(
    prefix="/api",
    tags=["strategy"],
)


@strategy_router.get("/strategy", response_model=list[StrategyPydanticModel])
async def get_strategies():
    async with Database() as async_session:
        fetch_strategy_query = await async_session.execute(select(StrategyModel))
        strategy_models = fetch_strategy_query.scalars().all()
        return strategy_models


@strategy_router.post("/strategy", response_model=StrategyPydanticModel)
async def post_strategy(
    strategy_pydantic_model: StrategyCreatePydanticModel,
    async_redis_client: Redis = Depends(get_async_redis_client),
):
    async with Database() as async_session:
        strategy_model = StrategyModel(**strategy_pydantic_model.model_dump())
        async_session.add(strategy_model)
        await async_session.flush()
        await async_session.refresh(strategy_model)

        redis_set_result = await async_redis_client.hset(
            str(strategy_model.id),
            "strategy",
            StrategyPydanticModel.model_validate(strategy_model).model_dump_json(),
        )
        if not redis_set_result:
            raise Exception(f"Redis set strategy: {strategy_model.id} failed")

        logging.info(f"{strategy_model.id} added to redis")

        return strategy_model
