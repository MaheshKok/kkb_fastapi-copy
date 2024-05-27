import logging

from app.database.schemas.order import OrderDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.angel_one import CreateOrderPydanticModel
from app.pydantic_models.angel_one import OrderDataPydModel
from app.pydantic_models.strategy import StrategyPydanticModel
from app.pydantic_models.trade import SignalPydanticModel


async def dump_angel_one_buy_order_in_db(
    *,
    order_data_pyd_model: OrderDataPydModel,
    strategy_pyd_model: StrategyPydanticModel,
    signal_pyd_model: SignalPydanticModel,
    crucial_details: str,
):
    async with Database() as async_session:
        create_order_pydantic_model = CreateOrderPydanticModel(
            order_id=order_data_pyd_model.orderid,
            unique_order_id=order_data_pyd_model.uniqueorderid,
            instrument=order_data_pyd_model.script,
            entry_received_at=signal_pyd_model.received_at,
            **strategy_pyd_model.model_dump(),
            **signal_pyd_model.model_dump(),
        )

        order_db_model = OrderDBModel(**create_order_pydantic_model.model_dump())
        async_session.add(order_db_model)
        await async_session.commit()
        logging.info(
            f"[ {crucial_details} ] - new angel one buy order: [{order_db_model.id}] added to DB"
        )
