import asyncio
import logging
import time
from pprint import pprint

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from oandapyV20.contrib.requests import MarketOrderRequest
from oandapyV20.endpoints.accounts import AccountInstruments
from oandapyV20.endpoints.orders import OrderCreate
from oandapyV20.endpoints.pricing import PricingInfo
from oandapyV20.endpoints.trades import TradeClose
from oandapyV20.endpoints.trades import TradesList
from sqlalchemy import select

from app.api.dependency import get_cfd_strategy_schema
from app.api.endpoints.trade import trading_router
from app.api.utils import update_capital_funds
from app.broker.Async_PyOanda import AsyncAPI
from app.database.models import BrokerModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import CFDStrategySchema
from app.schemas.trade import CFDPayloadSchema
from app.utils.in_memory_cache import oanda_access_token_cache
from app.utils.in_memory_cache import usd_to_gbp_conversion_cache


oanda_forex_router = APIRouter(
    prefix=f"{trading_router.prefix}/oanda",
    tags=["forex"],
)


account_mapping = {"101-004-28132533-002": "BCOUSD"}

logging.basicConfig(level=logging.INFO)


async def get_gbp_to_usd_conversion_rate():
    """
        example of response.json() = {
            "amount":1.0,
            "base":"EUR",
            "date":"2024-01-31",
            "rates":{
                    "GBP":0.85435,
                    "USD":1.0837
                    }
                }
        another api to explore is : https://freecurrencyapi.com/
        i.e https://api.freecurrencyapi.com/v1/latest?apikey=fca_live_ZH1BMAFdskOCtoOBuHo24UczlkYnrBuahfvpnVTn
        rate limit is 5000 per month
        response = requests.get('https://api.freecurrencyapi.com/v1/latest?apikey=fca_live_ZH1BMAFdskOCtoOBuHo24UczlkYnrBuahfvpnVTn')
        example of response = {
        "data": {
            "AUD": 1.5241902506,
            "BGN": 1.8086903075,
            "BRL": 4.9579508705,
            "CAD": 1.3434901525,
            "CHF": 0.8625901115,
            "CNY": 7.1686808567,
            "CZK": 22.9377044624,
            "DKK": 6.9000409472,
            "EUR": 0.9256900988,
            "GBP": 0.7889001143,
            "HKD": 7.8164709593,
            "HRK": 7.0212910435,
            "HUF": 355.0470230556,
            "IDR": 15765.351608207,
            "ILS": 3.646940704,
            "INR": 83.101800398,
            "ISK": 136.5275971048,
            "JPY": 146.9552778436,
            "KRW": 1332.9153596992,
            "MXN": 17.2135323715,
            "MYR": 4.7294009382,
            "NOK": 10.5120014574,
            "NZD": 1.6363202388,
            "PHP": 56.3089895248,
            "PLN": 4.0047706598,
            "RON": 4.6054606058,
            "RUB": 90.0425355249,
            "SEK": 10.4004410561,
            "SGD": 1.340580195,
            "THB": 35.6102562103,
            "TRY": 30.3617142214,
            "USD": 1,
            "ZAR": 18.6435724181,
        }
    }

    # In case needed in future
    #         response = await client.get(url="https://api.frankfurter.app/latest?to=USD,GBP")
    #         conversion_data = response.json()
    #         usd_to_gbp = conversion_data["rates"]["USD"] / conversion_data["rates"]["GBP"]

    """
    if "data" in usd_to_gbp_conversion_cache:
        conversion_data = usd_to_gbp_conversion_cache["data"]
    else:
        async with httpx.AsyncClient() as client:
            url = "https://api.freecurrencyapi.com/v1/latest?apikey=fca_live_ZH1BMAFdskOCtoOBuHo24UczlkYnrBuahfvpnVTn"
            response = await client.get(url=url)
            conversion_data = response.json()["data"]
            usd_to_gbp_conversion_cache["data"] = conversion_data

    gbp_to_usd = conversion_data["USD"] / conversion_data["GBP"]
    return gbp_to_usd


async def get_available_funds(
    strategy_schema: CFDStrategySchema, profit_or_loss: float, crucial_details: str
):
    conversion_rate = await get_gbp_to_usd_conversion_rate()
    available_funds = (strategy_schema.funds + profit_or_loss) * conversion_rate
    logging.info(f"[ {crucial_details} ] : Available funds are [ {available_funds} ]")
    return available_funds


async def get_current_instrument_price(
    client: AsyncAPI,
    cfd_payload_schema: CFDPayloadSchema,
    strategy_schema: CFDStrategySchema,
    crucial_details: str,
):
    """
         example of pricing_details = {
        "time": "2024-02-01T13:54:30.157768509Z",
        "prices": [
            {
                "type": "PRICE",
                "time": "2024-02-01T13:54:30.049843447Z",
                "bids": [{"price": "22.65500", "liquidity": 25000}],
                "asks": [{"price": "22.67300", "liquidity": 25000}],
                "closeoutBid": "22.65500",
                "closeoutAsk": "22.67300",
                "status": "tradeable",
                "tradeable": True,
                "quoteHomeConversionFactors": {
                    "positiveUnits": "0.78935943",
                    "negativeUnits": "0.78945914",
                },
                "instrument": "XAG_USD",
            }
        ],
    }
    """
    try:
        pricing_details = await client.request(
            PricingInfo(
                cfd_payload_schema.account_id,
                params={"instruments": [strategy_schema.instrument]},
            )
        )
    except Exception as e:
        logging.error(
            f"[ {crucial_details} ] : Failed to get current instrument price. Error: {e}"
        )
        return None

    if cfd_payload_schema.direction == SignalTypeEnum.SELL:
        current_instrument_price = float(pricing_details["prices"][0]["closeoutAsk"])
    else:
        current_instrument_price = float(pricing_details["prices"][0]["closeoutBid"])

    logging.info(
        f"[ {crucial_details} ] : Current instrument price is [ {current_instrument_price} ]"
    )
    return current_instrument_price


async def get_instrument(
    client: AsyncAPI,
    cfd_payload_schema: CFDPayloadSchema,
    strategy_schema: CFDStrategySchema,
    crucial_details: str,
):
    """
        instrument = {
        "name": "XAG_USD",
        "type": "METAL",
        "displayName": "Silver",
        "pipLocation": -4,
        "displayPrecision": 5,
        "tradeUnitsPrecision": 0,
        "minimumTradeSize": "1",
        "maximumTrailingStopDistance": "1.00000",
        "minimumTrailingStopDistance": "0.00050",
        "maximumPositionSize": "0",
        "maximumOrderUnits": "500000",
        "marginRate": "0.10",
        "guaranteedStopLossOrderMode": "ALLOWED",
        "minimumGuaranteedStopLossDistance": "0.0800",
        "guaranteedStopLossOrderExecutionPremium": "0.02999999999998",
        "guaranteedStopLossOrderLevelRestriction": {"volume": "25000", "priceRange": "0.25"},
        "tags": [
            {"type": "ASSET_CLASS", "name": "COMMODITY"},
            {"type": "KID_ASSET_CLASS", "name": "METAL"},
            {"type": "BRAIN_ASSET_CLASS", "name": "METAL"},
        ],
        "financing": {
            "longRate": "-0.0673",
            "shortRate": "0.0448",
            "financingDaysOfWeek": [
                {"dayOfWeek": "MONDAY", "daysCharged": 1},
                {"dayOfWeek": "TUESDAY", "daysCharged": 1},
                {"dayOfWeek": "WEDNESDAY", "daysCharged": 1},
                {"dayOfWeek": "THURSDAY", "daysCharged": 1},
                {"dayOfWeek": "FRIDAY", "daysCharged": 1},
                {"dayOfWeek": "SATURDAY", "daysCharged": 0},
                {"dayOfWeek": "SUNDAY", "daysCharged": 0},
            ],
        },
    }
    """
    instruments_request = AccountInstruments(cfd_payload_schema.account_id)
    instruments_response = await client.request(instruments_request)
    instruments = instruments_response["instruments"]
    # filter out instrument matching cfd_strategy_schema.instrument
    instrument_list = list(
        filter(lambda instrument: instrument["name"] == strategy_schema.instrument, instruments)
    )
    if not instrument_list:
        logging.error(
            f"[ {crucial_details} ] : No Instrument: [ {strategy_schema.instrument} ] found in the account: [ {cfd_payload_schema.account_id} ]"
        )
        return None
    else:
        instrument = instrument_list[0]
        logging.info(
            f"[ {crucial_details} ] : Instrument: [ {strategy_schema.instrument}] found in the account: [ {cfd_payload_schema.account_id} ]"
        )
        return instrument


async def get_lots_to_open(
    *,
    strategy_schema: CFDStrategySchema,
    profit_or_loss: float,
    cfd_payload_schema: CFDPayloadSchema,
    client: AsyncAPI,
    crucial_details: str,
):
    logging.info(f"[ {crucial_details} ] : Getting lots to open")

    available_funds, current_instrument_price, instrument = await asyncio.gather(
        get_available_funds(
            strategy_schema=strategy_schema,
            profit_or_loss=profit_or_loss,
            crucial_details=crucial_details,
        ),
        get_current_instrument_price(
            client=client,
            cfd_payload_schema=cfd_payload_schema,
            strategy_schema=strategy_schema,
            crucial_details=crucial_details,
        ),
        get_instrument(
            client=client,
            cfd_payload_schema=cfd_payload_schema,
            strategy_schema=strategy_schema,
            crucial_details=crucial_details,
        ),
    )

    if not available_funds or not current_instrument_price or not instrument:
        return None

    margin_required = float(instrument["marginRate"])
    logging.info(f"[ {crucial_details} ] : Margin required is [ {margin_required} ]")
    tradeUnitsPrecision = int(instrument["tradeUnitsPrecision"])

    if strategy_schema.compounding:
        logging.info(f"[ {crucial_details} ] : Compounding is enabled")
        # contracts worth that can be traded
        total_worth_of_contracts_to_trade = available_funds / margin_required
        lots_to_trade = round(
            total_worth_of_contracts_to_trade / current_instrument_price, tradeUnitsPrecision
        )
        logging.info(f"[ {crucial_details} ] : Lots : [ {lots_to_trade} ] to trade")
    else:
        logging.info(f"[ {crucial_details} ] : Compounding is disabled")
        fixed_lots_to_trade = strategy_schema.contracts
        funds_required_to_trade = current_instrument_price / margin_required * fixed_lots_to_trade

        if available_funds > funds_required_to_trade:
            logging.info(
                f"[ {crucial_details} ] : available funds : [ {available_funds} ] are greater than funds_required_to_trade : [ {funds_required_to_trade}], contracts : [ {fixed_lots_to_trade} ]"
            )
            lots_to_trade = round(fixed_lots_to_trade, tradeUnitsPrecision)
            logging.info(f"[ {crucial_details} ] : Hence we can trade Lots : [ {lots_to_trade} ]")
        else:
            # contracts worth that can be traded
            total_worth_of_contracts_to_trade = available_funds / margin_required
            lots_to_trade = round(
                total_worth_of_contracts_to_trade / current_instrument_price,
                tradeUnitsPrecision,
            )
            logging.info(f"[ {crucial_details} ] : Lots : [ {lots_to_trade} ] to trade")

    # if tradeUnitsPrecision == 0 then convert to int as decimal are not supported
    if tradeUnitsPrecision == 0:
        lots_to_trade = int(lots_to_trade)

    return lots_to_trade


async def get_oanda_access_token(cfd_strategy_schema: CFDStrategySchema, crucial_details: str):
    if cfd_strategy_schema.broker_id in oanda_access_token_cache:
        return oanda_access_token_cache[cfd_strategy_schema.broker_id]

    async with Database() as async_session:
        # fetch broker model from database
        stmt = select(BrokerModel).filter_by(id=cfd_strategy_schema.broker_id)
        _query = await async_session.execute(stmt)
        broker_model = _query.scalars().one_or_none()
        if not broker_model:
            msg = f"[ {crucial_details} ] : Broker model not found for broker_id: [ {cfd_strategy_schema.broker_id} ]"
            logging.error(msg)
            raise HTTPException(status_code=404, detail=msg)

        # set access token into oanda_access_token_cache
        oanda_access_token_cache[cfd_strategy_schema.broker_id] = broker_model.access_token
        return broker_model.access_token
        # access_token = "c1a1da5b257e3eb61082d88d6c41108d-3c1a484c1cf2b8ee215bef4e36807aad"


@oanda_forex_router.post("/cfd", status_code=200)
async def post_oanda_cfd(
    cfd_payload_schema: CFDPayloadSchema,
    cfd_strategy_schema: CFDStrategySchema = Depends(get_cfd_strategy_schema),
):
    start_time = time.perf_counter()
    demo_or_live = "DEMO" if cfd_strategy_schema.is_demo else "LIVE"

    crucial_details = (
        f"Oanda {demo_or_live} {cfd_strategy_schema.instrument} {cfd_payload_schema.direction}"
    )
    logging.info(f"[ {crucial_details} ] : signal received")

    access_token = await get_oanda_access_token(
        cfd_strategy_schema=cfd_strategy_schema, crucial_details=crucial_details
    )
    client = AsyncAPI(access_token=access_token)

    account_id = cfd_payload_schema.account_id
    trades = await client.request(TradesList(accountID=account_id))

    profit_or_loss_value = 0
    if trades["trades"]:
        for trade in trades["trades"]:
            trade_instrument = trade["instrument"]
            if trade_instrument == cfd_strategy_schema.instrument:
                current_open_lots = trade["currentUnits"]
                profit_or_loss_value = float(trade["unrealizedPL"])
                profit_or_loss_str = "profit" if profit_or_loss_value > 0 else "loss"
                logging.info(
                    f"[ {crucial_details} ] : current open lots: [ {current_open_lots} ] {profit_or_loss_str}: [ {profit_or_loss_value} ] to be closed"
                )
                # exit existing trades
                tradeID = trade["id"]
                close_trade_response = await client.request(
                    TradeClose(accountID=account_id, tradeID=tradeID)
                )
                if "orderFillTransaction" in close_trade_response:
                    trades_closed = close_trade_response["orderFillTransaction"]["tradesClosed"]
                    profit_or_loss_value = float(trades_closed[0]["realizedPL"])
                    profit_or_loss_str = "profit" if profit_or_loss_value > 0 else "loss"
                    logging.info(
                        f"[ {crucial_details} ] : current open lots: [ {current_open_lots} ] {profit_or_loss_str}: [ {profit_or_loss_value} ] closed"
                    )
                    await update_capital_funds(
                        cfd_strategy_schema=cfd_strategy_schema,
                        profit_or_loss=profit_or_loss_value,
                        crucial_details=crucial_details,
                    )
                else:
                    logging.error(
                        f"[ {crucial_details} ] : Error occured while closing existing trade, Error: {close_trade_response}"
                    )
                    pprint(close_trade_response)

    lots_to_open = await get_lots_to_open(
        strategy_schema=cfd_strategy_schema,
        profit_or_loss=profit_or_loss_value,
        cfd_payload_schema=cfd_payload_schema,
        client=client,
        crucial_details=crucial_details,
    )
    # buy new trades
    # buying lots in decimal is decided by 'tradeUnitsPrecision' if its 1 then upto 1 decimal is allowed
    # if its 0 then no decimal is allowed
    # instr_response = await client.request(AccountInstruments(accountID))

    is_buy_signal = cfd_payload_schema.direction == SignalTypeEnum.BUY
    market_order_request = MarketOrderRequest(
        instrument=cfd_strategy_schema.instrument,
        units=(int(lots_to_open) if is_buy_signal else -int(lots_to_open)),
    )
    response = await client.request(OrderCreate(account_id, data=market_order_request.data))
    long_or_short = "LONG" if is_buy_signal else "SHORT"
    if "orderFillTransaction" in response:
        msg = f"[ {crucial_details} ] : successfully [ {long_or_short}  {lots_to_open} ] trades."
        logging.info(msg)
    else:
        msg = f"[ {crucial_details} ] : Error occured while [ {long_or_short}  {lots_to_open} ] trades, Error: {response}"
        logging.error(msg)
        pprint(response)

    process_time = round(time.perf_counter() - start_time, 2)
    logging.info(f"[ {crucial_details} ] : request processing time: {process_time} seconds")
    return response
