import logging
import traceback
from datetime import date

import aioredis
from fastapi import HTTPException
from starlette import status

from app.api.trade.indian_fno.angel_one.redis_operations import get_angel_one_instrument_details
from app.api.trade.indian_fno.utils import get_strike_and_entry_price_from_option_chain
from app.broker_clients.async_angel_one import AsyncAngelOneClient
from app.pydantic_models.angel_one import DurationEnum
from app.pydantic_models.angel_one import ExchangeEnum
from app.pydantic_models.angel_one import OrderResponsePydModel
from app.pydantic_models.angel_one import OrderTypeEnum
from app.pydantic_models.angel_one import PlaceOrderPydanticModel
from app.pydantic_models.angel_one import ProductTypeEnum
from app.pydantic_models.angel_one import TransactionTypeEnum
from app.pydantic_models.angel_one import VarietyEnum
from app.pydantic_models.strategy import StrategyPydanticModel
from app.pydantic_models.trade import SignalPydanticModel
from app.utils.constants import OptionType


async def get_angel_one_trade_params(
    *,
    async_redis_client: aioredis.Redis,
    strategy_pyd_model: StrategyPydanticModel,
    expiry_date: date,
    is_fut: bool,
    strike: int = None,
    option_type: OptionType,
    transaction_type: TransactionTypeEnum,
):
    """
    Place an order with various parameters and constants.

    Order Constants:
    Here are several of the constant enum values used for placing orders.

    | Param            | Value         | Description                           |
    |------------------|---------------|---------------------------------------|
    | variety          | NORMAL        | Normal Order (Regular)                |
    |                  | STOPLOSS      | Stop loss order                       |
    |                  | AMO           | After Market Order                    |
    |                  | ROBO          | ROBO (Bracket Order)                  |
    |------------------|---------------|---------------------------------------|
    | transactiontype  | BUY           | Buy                                   |
    |                  | SELL          | Sell                                  |
    |------------------|---------------|---------------------------------------|
    | ordertype        | MARKET        | Market Order (MKT)                    |
    |                  | LIMIT         | Limit Order (L)                       |
    |                  | STOPLOSS_LIMIT| Stop Loss Limit Order (SL)            |
    |                  | STOPLOSS_MARKET| Stop Loss Market Order (SL-M)        |
    |------------------|---------------|---------------------------------------|
    | producttype      | DELIVERY      | Cash & Carry for equity (CNC)         |
    |                  | CARRYFORWARD  | Normal for futures and options (NRML) |
    |                  | MARGIN        | Margin Delivery                       |
    |                  | INTRADAY      | Margin Intraday Squareoff (MIS)       |
    |                  | BO            | Bracket Order (Only for ROBO)         |
    |------------------|---------------|---------------------------------------|
    | Duration         | DAY           | Regular Order                         |
    |                  | IOC           | Immediate or Cancel                   |
    |------------------|---------------|---------------------------------------|
    | exchange         | BSE           | BSE Equity                            |
    |                  | NSE           | NSE Equity                            |
    |                  | NFO           | NSE Future and Options                |
    |                  | MCX           | MCX Commodity                         |
    |                  | BFO           | BSE Futures and Options               |
    |                  | CDS           | Currency Derivate Segment             |

    Order Parameters:
    These parameters are common across different order varieties.

    | Param             | Description                                               |
    |-------------------|-----------------------------------------------------------|
    | tradingsymbol     | Trading Symbol of the instrument                          |
    |-------------------|-----------------------------------------------------------|
    | symboltoken       | Symbol Token is unique identifier                         |
    |-------------------|-----------------------------------------------------------|
    | Exchange          | Name of the exchange                                      |
    |-------------------|-----------------------------------------------------------|
    | transactiontype   | BUY or SELL                                               |
    |-------------------|-----------------------------------------------------------|
    | ordertype         | Order type (MARKET, LIMIT etc.)                           |
    |-------------------|-----------------------------------------------------------|
    | quantity          | Quantity to transact                                      |
    |-------------------|-----------------------------------------------------------|
    | producttype       | Product type (CNC, MIS)                                   |
    |-------------------|-----------------------------------------------------------|
    | price             | Min or max price to execute the order (for LIMIT orders)  |
    |-------------------|-----------------------------------------------------------|
    | triggerprice      | Price at which an order should be triggered (SL, SL-M)    |
    |-------------------|-----------------------------------------------------------|
    | squareoff         | Only For ROBO (Bracket Order)                             |
    |-------------------|-----------------------------------------------------------|
    | stoploss          | Only For ROBO (Bracket Order)                             |
    |-------------------|-----------------------------------------------------------|
    | trailingStopLoss  | Only For ROBO (Bracket Order)                             |
    |-------------------|-----------------------------------------------------------|
    | disclosedquantity | Quantity to disclose publicly (for equity trades)         |
    |-------------------|-----------------------------------------------------------|
    | duration          | Order duration (DAY, IOC)                                 |
    |-------------------|-----------------------------------------------------------|
    | ordertag          | Optional tag to apply to an order to identify it          |


    Place Order Request:
        {
            "variety":"NORMAL",
            "transactiontype":"BUY",
            "exchange":"NSE",
            "ordertype":"MARKET",
            "producttype":"INTRADAY",
            "duration":"DAY",

            "tradingsymbol":"SBIN-EQ",
            "symboltoken":"3045",
            "price":"194.50",
            "squareoff":"0",
            "stoploss":"0",
            "quantity":"1"
        }
    """

    strategy_pyd_model
    place_order_params = PlaceOrderPydanticModel(
        variety=VarietyEnum.NORMAL,
        transactiontype=transaction_type,
        ordertype=OrderTypeEnum.MARKET,
        producttype=ProductTypeEnum.CARRYFORWARD,
        duration=DurationEnum.IOC,
        exchange=ExchangeEnum.NFO,
    ).model_dump()

    angel_one_instrument_pyd_model = await get_angel_one_instrument_details(
        async_redis_client=async_redis_client,
        symbol=strategy_pyd_model.symbol,
        expiry_date=expiry_date,
        strike=strike,
        option_type=option_type,
        is_fut=is_fut,
    )

    place_order_params.update(
        {
            "tradingsymbol": angel_one_instrument_pyd_model.symbol,
            "symboltoken": angel_one_instrument_pyd_model.token,
            "quantity": strategy_pyd_model.min_quantity,
        }
    )
    return place_order_params


async def place_angel_one_buy_order(
    *,
    async_angelone_client: AsyncAngelOneClient,
    place_order_params: dict,
):
    response = await async_angelone_client.place_order(place_order_params)
    if response:
        return response.json()


async def create_angel_one_buy_order(
    *,
    async_angelone_client: AsyncAngelOneClient,
    async_redis_client: aioredis.Redis,
    strategy_pyd_model: StrategyPydanticModel,
    is_fut: bool,
    signal_pyd_model: SignalPydanticModel,
    crucial_details: str,
    option_chain: dict,
) -> OrderResponsePydModel:
    """
    Place Order Response:
            {
                "status": true,
                "message":"SUCCESS",
                "errorcode":"",
                "data": {
                            "script":"SBIN-EQ",
                            "orderid":"200910000000111",
                            "uniqueorderid":"34reqfachdfih"
                        }
            }
    """
    strike = None
    if not is_fut:
        strike, premium = await get_strike_and_entry_price_from_option_chain(
            option_chain=option_chain,
            signal_pyd_model=signal_pyd_model,
            premium=strategy_pyd_model.premium,
        )

    place_order_params = await get_angel_one_trade_params(
        async_redis_client=async_redis_client,
        strategy_pyd_model=strategy_pyd_model,
        expiry_date=signal_pyd_model.expiry,
        strike=strike,
        option_type=signal_pyd_model.option_type,
        is_fut=is_fut,
        transaction_type=signal_pyd_model.action.upper(),
    )

    try:
        response = await async_angelone_client.place_order(place_order_params)
        try:
            order_response_pyd_model = OrderResponsePydModel(**response)
            if order_response_pyd_model.status:
                if order_response_pyd_model.data:
                    return order_response_pyd_model
            else:
                msg = f"[ {crucial_details} ] - Error while placing angel one buy order: {order_response_pyd_model.message}"
                logging.error(msg)
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)
        except Exception:
            msg = f"[ {crucial_details} ] - Invalid response format from angel one buy order: {response}"
            logging.error(msg)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

    except HTTPException as e:
        logging.error(f"[ {crucial_details} ] - error while creating angel one buy order {e}")
        traceback.print_exc()
        raise HTTPException(status_code=e.status_code, detail=e.detail)
