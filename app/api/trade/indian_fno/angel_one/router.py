import json
import logging
import time
from typing import List

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends
from httpx import AsyncClient
from pydantic import TypeAdapter

from app.api.dependency import get_async_httpx_client
from app.api.dependency import get_async_redis_client
from app.api.dependency import get_strategy_pyd_model
from app.api.trade import trading_router
from app.api.trade.indian_fno.angel_one.db_operations import get_order_pyd_model
from app.api.trade.indian_fno.angel_one.db_operations import update_order_in_db
from app.api.trade.indian_fno.angel_one.dependency import get_async_angelone_client
from app.api.trade.indian_fno.angel_one.dependency import get_strategy_pyd_model_from_order
from app.api.trade.indian_fno.angel_one.local_trading_operations import (
    get_angel_one_pre_trade_kwargs,
)
from app.api.trade.indian_fno.angel_one.local_trading_operations import handle_futures_entry_order
from app.api.trade.indian_fno.angel_one.local_trading_operations import handle_futures_exit_order
from app.api.trade.indian_fno.angel_one.local_trading_operations import handle_options_entry_order
from app.api.trade.indian_fno.angel_one.local_trading_operations import handle_options_exit_order
from app.api.trade.indian_fno.angel_one.tasks import task_exit_angelone_trade_position
from app.api.trade.indian_fno.angel_one.tasks import task_open_angelone_trade_position
from app.api.trade.indian_fno.utils import get_crucial_details
from app.api.trade.indian_fno.utils import is_entry_order
from app.api.trade.indian_fno.utils import is_futures_strategy
from app.api.trade.indian_fno.utils import is_options_strategy
from app.api.trade.indian_fno.utils import is_order_complete
from app.broker_clients.async_angel_one import AsyncAngelOneClient
from app.database.session_manager.db_session import Database
from app.pydantic_models.angel_one import InitialOrderPydModel
from app.pydantic_models.angel_one import UpdatedOrderPydModel
from app.pydantic_models.strategy import StrategyPydModel
from app.pydantic_models.trade import RedisTradePydModel
from app.pydantic_models.trade import SignalPydModel


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

angel_one_router = APIRouter(
    prefix=f"{trading_router.prefix}",
    tags=["futures_and_options"],
)


@angel_one_router.post("/angelone/webhook/orders/updates", status_code=200)
async def angel_one_webhook_order_updates(
    updated_order_pyd_model: UpdatedOrderPydModel,
    async_redis_client: Redis = Depends(get_async_redis_client),
    initial_order_pyd_model: InitialOrderPydModel = Depends(get_order_pyd_model),
    strategy_pyd_model: StrategyPydModel = Depends(get_strategy_pyd_model_from_order),
    async_httpx_client: AsyncClient = Depends(get_async_httpx_client),
):
    logging.info(
        f"Received angelone webhook order updates for order_id: {updated_order_pyd_model.orderid} , unique_order_id: {initial_order_pyd_model.unique_order_id}"
    )

    crucial_details = f"{strategy_pyd_model.symbol} {strategy_pyd_model.id} {strategy_pyd_model.instrument_type} {initial_order_pyd_model.action}"
    valid_order_status = ["put order req received", "open", "open pending", "validation pending"]
    if updated_order_pyd_model.status in valid_order_status:
        msg = f"[ {crucial_details} ] - Skipping Intermittent order update for: {updated_order_pyd_model.orderid} at updatetime: {updated_order_pyd_model.updatetime}  with text: {updated_order_pyd_model.text}, status: {updated_order_pyd_model.status}, orderstatus: {updated_order_pyd_model.orderstatus}"
        logging.info(msg)
        return msg

    logging.info(
        f"[ {crucial_details} ] - order: {updated_order_pyd_model.orderid} executed at updatetime: {updated_order_pyd_model.updatetime}  with text: {updated_order_pyd_model.text}"
    )

    if is_futures_strategy(strategy_pyd_model):
        logging.info(
            f"[ {crucial_details} ] - Introduced slippage of {updated_order_pyd_model.price - initial_order_pyd_model.future_entry_price_received} for order: {updated_order_pyd_model.orderid}"
        )

    trade_id = None
    async with Database() as async_session:
        if is_order_complete(updated_order_pyd_model):
            if is_options_strategy(strategy_pyd_model):
                if is_entry_order(initial_order_pyd_model):
                    trade_id = await handle_options_entry_order(
                        async_session=async_session,
                        async_redis_client=async_redis_client,
                        initial_order_pyd_model=initial_order_pyd_model,
                        updated_order_pyd_model=updated_order_pyd_model,
                        strategy_pyd_model=strategy_pyd_model,
                        crucial_details=crucial_details,
                    )
                else:
                    trade_id = await handle_options_exit_order(
                        async_redis_client=async_redis_client,
                        initial_order_pyd_model=initial_order_pyd_model,
                        updated_order_pyd_model=updated_order_pyd_model,
                        strategy_pyd_model=strategy_pyd_model,
                        async_httpx_client=async_httpx_client,
                    )
            else:
                if is_entry_order(initial_order_pyd_model):
                    trade_id = await handle_futures_entry_order(
                        async_session=async_session,
                        async_redis_client=async_redis_client,
                        initial_order_pyd_model=initial_order_pyd_model,
                        updated_order_pyd_model=updated_order_pyd_model,
                        strategy_pyd_model=strategy_pyd_model,
                        crucial_details=crucial_details,
                    )
                else:
                    trade_id = await handle_futures_exit_order(
                        async_redis_client=async_redis_client,
                        initial_order_pyd_model=initial_order_pyd_model,
                        updated_order_pyd_model=updated_order_pyd_model,
                        strategy_pyd_model=strategy_pyd_model,
                        async_httpx_client=async_httpx_client,
                    )

        await update_order_in_db(
            async_session=async_session,
            initial_order_pyd_model=initial_order_pyd_model,
            updated_order_pyd_model=updated_order_pyd_model,
            crucial_details=crucial_details,
            trade_id=trade_id,
        )
        return "Order processed successfully"


@angel_one_router.post("/angelone/nfo", status_code=200)
async def post_nfo_angel_one_trading(
    signal_pyd_model: SignalPydModel,
    strategy_pyd_model: StrategyPydModel = Depends(get_strategy_pyd_model),
    async_redis_client: Redis = Depends(get_async_redis_client),
    async_httpx_client: AsyncClient = Depends(get_async_httpx_client),
    async_angelone_client: AsyncAngelOneClient = Depends(get_async_angelone_client),
):
    start_time = time.perf_counter()
    crucial_details = get_crucial_details(
        signal_pyd_model=signal_pyd_model, strategy_pyd_model=strategy_pyd_model
    )
    logging.info(f"[ {crucial_details} ] signal received")

    kwargs, redis_hash = await get_angel_one_pre_trade_kwargs(
        signal_pyd_model=signal_pyd_model,
        strategy_pyd_model=strategy_pyd_model,
        async_redis_client=async_redis_client,
    )
    kwargs["crucial_details"] = crucial_details

    trades_key = f"{signal_pyd_model.strategy_id}"
    msg = "successfully"
    if exiting_trades_json := await async_redis_client.hget(trades_key, redis_hash):
        exiting_trades_json_list = json.loads(exiting_trades_json)
        logging.info(
            f"[ {kwargs['crucial_details']} ] - Existing total: {len(exiting_trades_json_list)} trades to be closed"
        )
        redis_trade_pyd_model_list = TypeAdapter(List[RedisTradePydModel]).validate_python(
            [json.loads(trade) for trade in exiting_trades_json_list]
        )
        await task_exit_angelone_trade_position(
            **kwargs,
            async_angelone_client=async_angelone_client,
            redis_trade_pyd_model_list=redis_trade_pyd_model_list,
        )
        msg += " placed order to exit the position"
    else:
        await task_open_angelone_trade_position(
            **kwargs,
            async_angelone_client=async_angelone_client,
        )
        msg += " placed order to enter into position"

    process_time = round(time.perf_counter() - start_time, 2)
    logging.info(
        f"[ {kwargs['crucial_details']} ] - request processing time: {process_time} seconds"
    )
    return msg
