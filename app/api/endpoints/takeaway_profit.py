from typing import List

from fastapi import APIRouter
from sqlalchemy import select

from app.database.models import TakeAwayProfitModel
from app.database.session_manager.db_session import Database
from app.schemas.take_away_profit import TakeAwayProfitSchema


takeaway_profit = APIRouter(
    prefix="/api/takeaway_profit",
    tags=["takeaway_profit"],
)


@takeaway_profit.get("", response_model=List[TakeAwayProfitSchema])
async def get_takeaway_profit():
    async with Database() as async_session:
        fetch_takeaway_profit_query = await async_session.execute(select(TakeAwayProfitModel))
        takeaway_profit_models = fetch_takeaway_profit_query.scalars().all()
        return takeaway_profit_models
