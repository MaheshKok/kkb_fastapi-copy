from aioredis import Redis
from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import db
from app.database.models import StrategyModel
from app.schemas.trade import EntryTradeSchema


def get_app(request: Request) -> FastAPI:
    return request.app


async def get_async_session(app: FastAPI = Depends(get_app)) -> AsyncSession:
    async_session = app.state.async_session_maker()
    yield async_session


async def is_valid_strategy(trade_post_schema: EntryTradeSchema):
    # query database to check if strategy_id exists
    _query = select(StrategyModel).where(StrategyModel.id == trade_post_schema.strategy_id)
    result = await db.session.execute(_query)
    strategy_model = result.scalars().one_or_none()

    if not strategy_model:
        raise HTTPException(status_code=400, detail="Invalid strategy_id")
    return strategy_model


async def get_async_redis(app: FastAPI = Depends(get_app)) -> Redis:
    yield app.state.async_redis
