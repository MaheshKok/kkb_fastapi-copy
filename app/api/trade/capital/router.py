import logging
import time

from fastapi import APIRouter
from fastapi import Depends

from app.api.dependency import get_cfd_strategy_pyd_model
from app.api.trade import trading_router
from app.api.trade.capital.tasks import close_capital_lots
from app.api.trade.capital.tasks import open_capital_lots
from app.api.trade.capital.utils import get_capital_cfd_existing_profit_or_loss
from app.broker_clients.async_capital import AsyncCapitalClient
from app.pydantic_models.strategy import CFDStrategyPydanticModel
from app.pydantic_models.trade import CFDPayloadPydanticModel


forex_router = APIRouter(
    prefix=f"{trading_router.prefix}/cfd",
    tags=["forex"],
)


@forex_router.post("/", status_code=200)
async def post_capital_cfd(
    cfd_payload_pyd_model: CFDPayloadPydanticModel,
    cfd_strategy_pyd_model: CFDStrategyPydanticModel = Depends(get_cfd_strategy_pyd_model),
):
    start_time = time.perf_counter()

    demo_or_live = "DEMO" if cfd_strategy_pyd_model.is_demo else "LIVE"
    crucial_details = f"Capital {demo_or_live} {cfd_strategy_pyd_model.instrument} {cfd_payload_pyd_model.direction}"

    logging.info(f"[ {crucial_details} ] : signal received")

    client = AsyncCapitalClient(
        username="maheshkokare100@gmail.com",
        password="SUua9Ydc83G.i!d",
        api_key="qshPG64m0RCWQ3fe",
        demo=cfd_strategy_pyd_model.is_demo,
    )

    profit_or_loss, current_open_lots, direction = await get_capital_cfd_existing_profit_or_loss(
        client, cfd_strategy_pyd_model, crucial_details
    )

    if current_open_lots:
        position_reversed = await close_capital_lots(
            client=client,
            cfd_strategy_pyd_model=cfd_strategy_pyd_model,
            cfd_payload_pyd_model=cfd_payload_pyd_model,
            demo_or_live=demo_or_live,
            lots_to_close=current_open_lots,
            profit_or_loss=profit_or_loss,
            crucial_details=crucial_details,
        )

        if position_reversed:
            msg = f"[ {crucial_details} ] - lots [ {current_open_lots} ] are reversed in [ {direction} ] direction, hence skipped opening new positions"
            logging.info(msg)
            process_time = time.perf_counter() - start_time
            logging.info(
                f"[ {crucial_details} ] - request processing time: {process_time} seconds"
            )
            return msg

    if direction != cfd_payload_pyd_model.direction.upper():
        # funds_to_use = await get_funds_to_use(client, cfd_strategy_pyd_model)

        await open_capital_lots(
            client=client,
            cfd_strategy_pyd_model=cfd_strategy_pyd_model,
            cfd_payload_pyd_model=cfd_payload_pyd_model,
            demo_or_live=demo_or_live,
            profit_or_loss=profit_or_loss,
            funds_to_use=0.0,
            crucial_details=crucial_details,
        )
        process_time = time.perf_counter() - start_time
        logging.info(f"[ {crucial_details} ] : request processing time: {process_time} seconds")
    else:
        msg = f"[ {crucial_details} ] - signal [ {cfd_payload_pyd_model.direction} ] is same as current direction, hence skipping opening new positions"
        logging.info(msg)
        return msg
