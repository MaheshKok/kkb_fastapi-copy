import logging

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy import select

from app.api.dependency import get_async_redis_client
from app.database.schemas import StrategyDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.strategy import StrategyCreatePydModel
from app.pydantic_models.strategy import StrategyPydModel


strategy_router = APIRouter(
    prefix="/api",
    tags=["strategy"],
)


@strategy_router.get("/strategy", response_model=list[StrategyPydModel])
async def get_strategies():
    async with Database() as async_session:
        fetch_strategy_query = await async_session.execute(select(StrategyDBModel))
        strategy_db_models = fetch_strategy_query.scalars().all()
        return strategy_db_models


@strategy_router.post("/strategy", response_model=StrategyPydModel)
async def post_strategy(
    strategy_pyd_model: StrategyCreatePydModel,
    async_redis_client: Redis = Depends(get_async_redis_client),
):
    async with Database() as async_session:
        strategy_db_model = StrategyDBModel(**strategy_pyd_model.model_dump())
        async_session.add(strategy_db_model)
        await async_session.flush()
        await async_session.refresh(strategy_db_model)

        redis_set_result = await async_redis_client.hset(
            str(strategy_db_model.id),
            "strategy",
            StrategyPydModel.model_validate(strategy_db_model).model_dump_json(),
        )
        if not redis_set_result:
            raise Exception(f"Redis set strategy: {strategy_db_model.id} failed")

        logging.info(f"{strategy_db_model.id} added to redis")

        return strategy_db_model
