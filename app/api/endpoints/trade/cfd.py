import logging

from fastapi import APIRouter
from fastapi import Depends

from app.api.dependency import get_cfd_strategy_schema
from app.api.endpoints.trade import trading_router
from app.api.utils import close_capital_lots
from app.api.utils import get_capital_cfd_existing_profit_or_loss
from app.api.utils import get_funds_to_use
from app.api.utils import open_capital_lots
from app.broker.AsyncCapital import AsyncCapitalClient
from app.schemas.strategy import CFDStrategySchema
from app.schemas.trade import CFDPayloadSchema


forex_router = APIRouter(
    prefix=f"{trading_router.prefix}/cfd",
    tags=["forex"],
)


@forex_router.post("/", status_code=200)
async def post_cfd(
    cfd_payload_schema: CFDPayloadSchema,
    cfd_strategy_schema: CFDStrategySchema = Depends(get_cfd_strategy_schema),
):
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"
    logging.info(
        f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : signal [ {cfd_payload_schema.direction} ] received"
    )

    client = AsyncCapitalClient(
        username="maheshkokare100@gmail.com",
        password="SUua9Ydc83G.i!d",
        api_key="qshPG64m0RCWQ3fe",
        demo=cfd_strategy_schema.is_demo,
    )

    profit_or_loss, current_open_lots, direction = await get_capital_cfd_existing_profit_or_loss(
        client, cfd_strategy_schema
    )

    if current_open_lots:
        position_reversed = await close_capital_lots(
            client=client,
            cfd_strategy_schema=cfd_strategy_schema,
            cfd_payload_schema=cfd_payload_schema,
            demo_or_live=demo_or_live,
            lots_to_close=current_open_lots,
            profit_or_loss=profit_or_loss,
        )

        if position_reversed:
            msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : lots [ {current_open_lots} ] are reversed in [ {direction} ] direction,  hence skipping opening new positions"
            logging.info(msg)
            return msg

    if direction != cfd_payload_schema.direction.upper():
        funds_to_use = await get_funds_to_use(client, cfd_strategy_schema)

        return await open_capital_lots(
            client=client,
            cfd_strategy_schema=cfd_strategy_schema,
            cfd_payload_schema=cfd_payload_schema,
            demo_or_live=demo_or_live,
            profit_or_loss=profit_or_loss,
            funds_to_use=funds_to_use,
        )
    else:
        msg = f"[ {demo_or_live} {cfd_strategy_schema.instrument} ] : signal [ {cfd_payload_schema.direction} ] is same as current direction, hence skipping opening new positions"
        logging.info(msg)
        return msg
