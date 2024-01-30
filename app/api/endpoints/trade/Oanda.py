from fastapi import APIRouter
from fastapi import Depends
from oandapyV20.contrib.requests import MarketOrderRequest
from oandapyV20.contrib.requests import TradeCloseRequest
from oandapyV20.endpoints.orders import OrderCreate
from oandapyV20.endpoints.trades import TradeClose
from oandapyV20.endpoints.trades import TradesList

from app.api.dependency import get_cfd_strategy_schema
from app.api.endpoints.trade import trading_router
from app.api.utils import get_lots_to_trade_and_profit_or_loss
from app.api.utils import update_capital_funds
from app.broker.Async_PyOanda import AsyncAPI
from app.schemas.strategy import CFDStrategySchema
from app.schemas.trade import CFDPayloadSchema


oanda_forex_router = APIRouter(
    prefix=f"{trading_router.prefix}/oanda",
    tags=["forex"],
)


account_mapping = {"101-004-28132533-002": "BCOUSD"}


@oanda_forex_router.post("/cfd", status_code=200)
async def post_cfd(
    cfd_payload_schema: CFDPayloadSchema,
    cfd_strategy_schema: CFDStrategySchema = Depends(get_cfd_strategy_schema),
):
    access_token = "c1a1da5b257e3eb61082d88d6c41108d-3c1a484c1cf2b8ee215bef4e36807aad"
    client = AsyncAPI(access_token=access_token)
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"

    account_id = cfd_payload_schema.account_id
    trades = await client.request(TradesList(account_id=account_id))

    profit_or_loss = 0
    if trades["trades"]:
        # exit existing trades
        close_trade_request = TradeCloseRequest()
        close_trade_response = await client.request(TradeClose(close_trade_request.data))
        if "orderFillTransaction" in close_trade_response.response:
            trades_closed = close_trade_response["orderFillTransaction"]["trades_closed"]
            profit_or_loss = trades_closed[0]["realizedPL"]
            await update_capital_funds(
                cfd_strategy_schema=cfd_strategy_schema,
                demo_or_live=demo_or_live,
                profit_or_loss=profit_or_loss,
            )

    lots_to_open, update_profit_or_loss_in_db = get_lots_to_trade_and_profit_or_loss(
        0, cfd_strategy_schema, profit_or_loss
    )
    # buy new trades
    market_order_request = MarketOrderRequest(
        instrument=cfd_strategy_schema.instrument,
        units=lots_to_open,
    )
    response = await client.request(OrderCreate(account_id, data=market_order_request.data))
    return response
