import datetime
import json
import logging
import time
from typing import Any
from typing import List

from aioredis import Redis
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import TypeAdapter
from sqlalchemy import update

from app.api.dependency import get_async_httpx_client
from app.api.dependency import get_async_redis_client
from app.api.dependency import get_strategy_pyd_model
from app.api.trade import trading_router
from app.api.trade.indian_fno.angel_one.db_operations import get_order_pyd_model
from app.api.trade.indian_fno.angel_one.dependency import get_async_angelone_client
from app.api.trade.indian_fno.angel_one.dependency import get_strategy_pyd_model_from_order
from app.api.trade.indian_fno.angel_one.tasks import task_exit_angelone_trade_position
from app.api.trade.indian_fno.angel_one.tasks import task_open_angelone_trade_position
from app.api.trade.indian_fno.angel_one.trading_operations import get_expiry_date_to_trade
from app.api.trade.indian_fno.utils import calculate_profits
from app.api.trade.indian_fno.utils import close_trades_in_db_and_remove_from_redis
from app.api.trade.indian_fno.utils import get_crucial_details
from app.api.trade.indian_fno.utils import get_current_and_next_expiry_from_redis
from app.api.trade.indian_fno.utils import get_future_price
from app.api.trade.indian_fno.utils import get_opposite_trade_option_type
from app.api.trade.indian_fno.utils import is_entry_order
from app.api.trade.indian_fno.utils import is_futures_strategy
from app.api.trade.indian_fno.utils import is_order_complete
from app.api.trade.indian_fno.utils import is_short_strategy
from app.api.trade.indian_fno.utils import push_trade_to_redis
from app.api.trade.indian_fno.utils import set_option_type
from app.broker_clients.async_angel_one import AsyncAngelOneClient
from app.database.schemas import OrderDBModel
from app.database.schemas import TradeDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.angel_one import InitialOrderPydModel
from app.pydantic_models.angel_one import UpdatedOrderPydModel
from app.pydantic_models.enums import InstrumentTypeEnum
from app.pydantic_models.enums import OptionTypeEnum
from app.pydantic_models.enums import PositionEnum
from app.pydantic_models.enums import SignalTypeEnum
from app.pydantic_models.strategy import StrategyPydModel
from app.pydantic_models.trade import EntryTradePydModel
from app.pydantic_models.trade import RedisTradePydModel
from app.pydantic_models.trade import SignalPydModel
from app.utils.constants import FUT


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

    async with Database() as async_session:
        # Use the AsyncSession to perform database operations
        # Example: Create a new entry in the database
        if is_order_complete(updated_order_pyd_model):
            if is_entry_order(initial_order_pyd_model):
                trade_pyd_model = EntryTradePydModel(
                    entry_price=updated_order_pyd_model.averageprice,
                    future_entry_price=initial_order_pyd_model.future_entry_price_received,
                    # TODO: check quantity when multiple lots are bought
                    quantity=updated_order_pyd_model.quantity,
                    entry_at=initial_order_pyd_model.entry_at,
                    instrument=updated_order_pyd_model.tradingsymbol,
                    entry_received_at=initial_order_pyd_model.entry_received_at,
                    # reason to include received_at is because it is inherited from signalpydmodel
                    received_at=initial_order_pyd_model.entry_received_at,
                    expiry=initial_order_pyd_model.expiry,
                    action=initial_order_pyd_model.action,
                    strategy_id=strategy_pyd_model.id,
                    future_entry_price_received=initial_order_pyd_model.future_entry_price_received,
                    strike=initial_order_pyd_model.strike,
                    option_type=initial_order_pyd_model.option_type,
                )

                trade_db_model = TradeDBModel(
                    **trade_pyd_model.model_dump(
                        exclude={
                            "premium",
                            "broker_id",
                            "symbol",
                            "received_at",
                            "future_entry_price",
                        },
                        exclude_none=True,
                    )
                )
                async_session.add(trade_db_model)
                await async_session.flush([trade_db_model])
                msg = f"[ {crucial_details} ] - new trade: [ {trade_db_model.id} ] added to DB"
                logging.info(msg)

                # TODO: enable once testing is done
                await push_trade_to_redis(
                    async_redis_client=async_redis_client,
                    trade_db_model=trade_db_model,
                    signal_type=initial_order_pyd_model.action,
                    crucial_details=crucial_details,
                )
            else:
                exit_price = updated_order_pyd_model.averageprice
                # construct signal pyd model the way we receive it from tradingview
                # action will be the opposite of the initial_order_pyd_model.action, replace action with position and when constructing signal action then with strategy position and
                action = (
                    SignalTypeEnum.BUY
                    if initial_order_pyd_model.action == SignalTypeEnum.SELL
                    else SignalTypeEnum.SELL
                )
                if is_futures_strategy(strategy_pyd_model=strategy_pyd_model):
                    pass
                else:
                    if is_short_strategy(strategy_pyd_model=strategy_pyd_model):
                        if initial_order_pyd_model.option_type == OptionTypeEnum.CE:
                            action = SignalTypeEnum.BUY
                        else:
                            action = SignalTypeEnum.SELL
                    else:
                        if initial_order_pyd_model.option_type == OptionTypeEnum.CE:
                            action = SignalTypeEnum.SELL
                        else:
                            action = SignalTypeEnum.BUY

                # now received_at will the time when angelone pushes the order updates
                signal_pyd_model = SignalPydModel(
                    strategy_id=strategy_pyd_model.id,
                    future_entry_price_received=initial_order_pyd_model.future_entry_price_received,
                    received_at=datetime.datetime.utcnow(),
                    action=action,
                )

                crucial_details = get_crucial_details(
                    signal_pyd_model=signal_pyd_model, strategy_pyd_model=strategy_pyd_model
                )
                kwargs, redis_hash = await get_angel_one_pre_trade_kwargs(
                    signal_pyd_model=signal_pyd_model,
                    strategy_pyd_model=strategy_pyd_model,
                    async_redis_client=async_redis_client,
                )
                kwargs["crucial_details"] = crucial_details

                if not is_futures_strategy(strategy_pyd_model=strategy_pyd_model):
                    strike_exit_price_dict = {initial_order_pyd_model.strike: exit_price}
                    future_exit_price = await get_future_price(
                        async_redis_client=async_redis_client,
                        strategy_pyd_model=strategy_pyd_model,
                        expiry_date=kwargs["futures_expiry_date"],
                        signal_pyd_model=signal_pyd_model,
                        async_httpx_client=async_httpx_client,
                    )

                    logging.info(
                        f"[ {crucial_details} ] - Slippage: [ {future_exit_price - signal_pyd_model.future_entry_price_received} points ] introduced for future_exit_price: [ {signal_pyd_model.future_entry_price_received} ] "
                    )
                    trades_key = f"{signal_pyd_model.strategy_id}"
                    exiting_trades_json = await async_redis_client.hget(trades_key, redis_hash)
                    # initiate exit_trade
                    exiting_trades_json_list = json.loads(exiting_trades_json)
                    logging.info(
                        f"[ {kwargs['crucial_details']} ] - Existing total: {len(exiting_trades_json_list)} trades to be closed"
                    )
                    redis_trade_pyd_model_list = TypeAdapter(
                        List[RedisTradePydModel]
                    ).validate_python([json.loads(trade) for trade in exiting_trades_json_list])

                    (
                        updated_data,
                        total_ongoing_profit,
                        total_future_profit,
                    ) = await calculate_profits(
                        strike_exit_price_dict=strike_exit_price_dict,
                        future_exit_price=future_exit_price,
                        signal_pyd_model=signal_pyd_model,
                        redis_trade_pyd_model_list=redis_trade_pyd_model_list,
                        strategy_pyd_model=strategy_pyd_model,
                    )
                    logging.info(
                        f" [ {crucial_details} ] - adding profit: [ {total_ongoing_profit} ] and future profit: [ {total_future_profit} ]"
                    )

                    # update database with the updated data
                    await close_trades_in_db_and_remove_from_redis(
                        updated_data=updated_data,
                        strategy_pyd_model=strategy_pyd_model,
                        total_profit=total_ongoing_profit,
                        total_future_profit=total_future_profit,
                        total_redis_trades=len(redis_trade_pyd_model_list),
                        async_redis_client=async_redis_client,
                        redis_strategy_key_hash=f"{trades_key} {redis_hash}",
                        crucial_details=crucial_details,
                    )

                    # TODO: dont move get_async_angelone_client as dependency
                    #  because strategy_pyd_model is dependant on signal_pyd_model
                    #  which is not available in this request
                    async_angelone_client = await get_async_angelone_client(
                        async_redis_client=async_redis_client,
                        strategy_pyd_model=strategy_pyd_model,
                    )
                    # update kwargs with
                    kwargs["ongoing_profit"] = total_ongoing_profit
                    await task_open_angelone_trade_position(
                        **kwargs,
                        async_angelone_client=async_angelone_client,
                    )

        # Update the order with new status and text
        update_query = (
            update(OrderDBModel)
            .where(OrderDBModel.unique_order_id == initial_order_pyd_model.unique_order_id)
            .values(
                status=updated_order_pyd_model.status,
                orderstatus=updated_order_pyd_model.orderstatus,
                text=updated_order_pyd_model.text,
                executed_price=updated_order_pyd_model.averageprice,
            )
        )
        await async_session.execute(update_query)
        await async_session.commit()
        logging.info(
            f"[ {crucial_details} ] - order: {initial_order_pyd_model.unique_order_id} updated in DB"
        )
        return "Order processed successfully"


async def get_angel_one_pre_trade_kwargs(
    *,
    signal_pyd_model: SignalPydModel,
    strategy_pyd_model: StrategyPydModel,
    async_redis_client: Redis,
) -> tuple[dict[str, SignalPydModel | StrategyPydModel | Redis | str | Any], str]:
    todays_date = datetime.datetime.utcnow().date()
    kwargs = {
        "signal_pyd_model": signal_pyd_model,
        "strategy_pyd_model": strategy_pyd_model,
        "async_redis_client": async_redis_client,
    }

    (
        current_futures_expiry_date,
        next_futures_expiry_date,
        is_today_futures_expiry,
    ) = await get_current_and_next_expiry_from_redis(
        async_redis_client=async_redis_client,
        instrument_type=InstrumentTypeEnum.FUTIDX,
        symbol=strategy_pyd_model.symbol,
    )

    if (
        strategy_pyd_model.only_on_expiry
        and strategy_pyd_model.instrument_type == InstrumentTypeEnum.FUTIDX
        and current_futures_expiry_date != todays_date
    ):
        raise HTTPException(status_code=403, detail="Only on expiry")

    futures_expiry_date = get_expiry_date_to_trade(
        current_expiry_date=current_futures_expiry_date,
        next_expiry_date=next_futures_expiry_date,
        strategy_pyd_model=strategy_pyd_model,
        is_today_expiry=is_today_futures_expiry,
    )

    # fetch opposite position-based trades
    redis_hash = f"{futures_expiry_date} {PositionEnum.SHORT if signal_pyd_model.action == SignalTypeEnum.BUY else PositionEnum.LONG} {FUT}"
    signal_pyd_model.expiry = futures_expiry_date
    kwargs.update(
        {
            "futures_expiry_date": futures_expiry_date,
        }
    )

    if strategy_pyd_model.instrument_type == InstrumentTypeEnum.OPTIDX:
        set_option_type(strategy_pyd_model, signal_pyd_model)
        (
            current_options_expiry_date,
            next_options_expiry_date,
            is_today_options_expiry,
        ) = await get_current_and_next_expiry_from_redis(
            async_redis_client=async_redis_client,
            instrument_type=InstrumentTypeEnum.OPTIDX,
            symbol=strategy_pyd_model.symbol,
        )

        if (
            strategy_pyd_model.only_on_expiry
            and strategy_pyd_model.instrument_type == InstrumentTypeEnum.OPTIDX
        ):
            if current_options_expiry_date != todays_date:
                return {"message": "Only on expiry"}

            if datetime.datetime.utcnow().time() >= datetime.time(hour=9, minute=45):
                return {"message": "Cannot Trade after 9:45AM GMT on Expiry"}

        options_expiry_date = get_expiry_date_to_trade(
            current_expiry_date=current_options_expiry_date,
            next_expiry_date=next_options_expiry_date,
            strategy_pyd_model=strategy_pyd_model,
            is_today_expiry=is_today_options_expiry,
        )
        # fetch opposite position-based trades
        opposite_trade_option_type = get_opposite_trade_option_type(
            strategy_pyd_model.position, signal_pyd_model.action
        )
        redis_hash = f"{options_expiry_date} {opposite_trade_option_type}"
        signal_pyd_model.expiry = options_expiry_date
        kwargs.update(
            {
                "options_expiry_date": options_expiry_date,
            }
        )

    return kwargs, redis_hash


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
        # initiate exit_trade
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
        # initiate buy_trade
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
