from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import Row
from sqlalchemy import RowMapping
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Strategy
from app.schemas.trade import TradePostSchema


def get_app(request: Request) -> FastAPI:
    return request.app


async def get_async_session(app: FastAPI = Depends(get_app)) -> AsyncSession:
    async_session = app.state.async_session_maker()
    try:
        async with async_session.begin():
            yield async_session
    finally:
        await async_session.close()


async def is_valid_strategy(
    payload: TradePostSchema, db: AsyncSession = Depends(get_async_session)
) -> Row | RowMapping:
    # query database to check if strategy_id exists
    stmt = select(Strategy).where(Strategy.id == payload.strategy_id)
    result = await db.execute(stmt)
    strategy_db = result.scalars().one_or_none()

    if not strategy_db:
        raise HTTPException(status_code=400, detail="Invalid strategy_id")
    return strategy_db
