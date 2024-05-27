from fastapi import Depends
from sqlalchemy import select

from app.api.trade.indian_fno.angel_one.db_operations import get_order_pyd_model
from app.database.schemas import StrategyDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.angel_one import InitialOrderPydModel
from app.pydantic_models.strategy import StrategyPydModel


async def get_strategy_pyd_model_from_order(
    initial_order_pyd_model: InitialOrderPydModel = Depends(get_order_pyd_model),
) -> StrategyPydModel:
    async with Database() as async_session:
        fetch_strategy_query = await async_session.execute(
            select(StrategyDBModel).filter_by(id=initial_order_pyd_model.strategy_id)
        )
        strategy_db_model = fetch_strategy_query.scalars().one()
        if not strategy_db_model:
            raise Exception(f"Strategy: [ {initial_order_pyd_model.instrument} ] not found in DB")
        return StrategyPydModel.model_validate(strategy_db_model)
