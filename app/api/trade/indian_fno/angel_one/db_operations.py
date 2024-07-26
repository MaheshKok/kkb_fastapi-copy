import logging

from sqlalchemy import text

from app.database.schemas.order import OrderDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.angel_one import EntryExitEnum
from app.pydantic_models.angel_one import InitialOrderPydModel
from app.pydantic_models.angel_one import OrderDataPydModel
from app.pydantic_models.angel_one import UpdatedOrderPydModel
from app.pydantic_models.strategy import StrategyPydModel
from app.pydantic_models.trade import SignalPydModel


async def dump_angel_one_order_in_db(
    *,
    order_data_pyd_model: OrderDataPydModel,
    strategy_pyd_model: StrategyPydModel,
    signal_pyd_model: SignalPydModel,
    crucial_details: str,
    entry_exit: EntryExitEnum,
):
    async with Database() as async_session:
        create_order_pyd_model = InitialOrderPydModel(
            order_id=order_data_pyd_model.orderid,
            unique_order_id=order_data_pyd_model.uniqueorderid,
            instrument=order_data_pyd_model.script,
            entry_received_at=signal_pyd_model.received_at,
            entry_exit=entry_exit,
            **strategy_pyd_model.model_dump(),
            **signal_pyd_model.model_dump(),
        )

        order_db_model = OrderDBModel(**create_order_pyd_model.model_dump())
        async_session.add(order_db_model)
        await async_session.commit()
        logging.info(
            f"[ {crucial_details} ] - new angel_one order: [{order_db_model.unique_order_id}] added to DB"
        )


async def get_order_pyd_model(
    updated_order_pyd_model: UpdatedOrderPydModel,
) -> InitialOrderPydModel:
    # # wait for two second for the order to be created in the DB
    # await asyncio.sleep(1)
    async with Database() as async_session:
        # TODO: for some reason, it is throwing an error i.e. 'Unknown PG numeric type: 1043' because of orderid,
        #  hence swithed to raw sql
        # fetch_order_query = await async_session.execute(
        #     select(OrderDBModel).filter_by(order_id=updated_order_pyd_model.orderid)
        # )
        fetch_order_query = await async_session.execute(
            text('SELECT * FROM "order" WHERE order_id = :order_id'),
            {"order_id": updated_order_pyd_model.orderid},
        )
        order_db_model = fetch_order_query.fetchone()
        if not order_db_model:
            raise Exception(
                f"Angel One Order: [ {updated_order_pyd_model.orderid} ] not found in DB"
            )
        return InitialOrderPydModel.model_validate(order_db_model)
