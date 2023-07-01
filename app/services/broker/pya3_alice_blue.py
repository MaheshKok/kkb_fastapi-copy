import asyncio
import datetime
import json
import logging
from collections import defaultdict

import httpx
from aioredis import Redis
from fastapi import HTTPException
from fastapi_sa.database import db
from httpx import AsyncClient
from pya3 import Aliceblue
from pya3 import Instrument
from pya3 import OrderType
from pya3 import ProductType
from pya3 import TransactionType
from pya3 import encrypt_string
from sqlalchemy import select

from app.database.models import BrokerModel
from app.schemas.broker import BrokerSchema
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.utils.constants import ALICE_BLUE_DATE_FORMAT
from app.utils.constants import FUT
from app.utils.constants import OptionType
from app.utils.constants import Status


log = logging.getLogger(__name__)


class Pya3Aliceblue(Aliceblue):
    def __init__(
        self, user_id, api_key, async_httpx_client, base=None, session_id=None, disable_ssl=False
    ):
        super().__init__(user_id, api_key, base, session_id, disable_ssl)
        self.async_httpx_client = async_httpx_client

    async def _get(self, sub_url, data=None):
        """Get method declaration"""
        url = self.base + self._sub_urls[sub_url]
        return await self._request(url, "GET", data=data)

    async def _post(self, sub_url, data=None):
        """Post method declaration"""
        url = self.base + self._sub_urls[sub_url]
        return await self._request(url, "POST", data=data)

    async def _dummypost(self, url, data=None):
        """Post method declaration"""
        return await self._request(url, "POST", data=data)

    async def _request(self, method, req_type, data=None):
        """
        Headers with authorization. For some requests authorization
        is not required. It will be sent as an empty String
        """
        _headers = {
            "X-SAS-Version": "2.0",
            "User-Agent": self._user_agent(),
            "Authorization": self._user_authorization(),
        }
        try:
            if req_type == "POST":
                response = await self.async_httpx_client.post(method, json=data, headers=_headers)
            elif req_type == "GET":
                response = await self.async_httpx_client.get(method, headers=_headers)
            else:
                return {"stat": "Not_ok", "emsg": "Invalid request type", "encKey": None}

            if response.status_code == 200:
                return response.json()
            else:
                emsg = str(response.status_code) + " - " + response.reason_phrase
                return {"stat": "Not_ok", "emsg": emsg, "encKey": None}

        except (httpx.RequestError, asyncio.TimeoutError) as exception:
            return {"stat": "Not_ok", "emsg": str(exception), "encKey": None}

    """Method to call  Place Order"""

    async def place_order(
        self,
        transaction_type,
        instrument,
        quantity,
        order_type,
        product_type,
        price=0.0,
        trigger_price=None,
        stop_loss=None,
        square_off=None,
        trailing_sl=None,
        is_amo=False,
        order_tag=None,
        is_ioc=False,
    ):
        if transaction_type is None:
            raise TypeError("Required parameter transaction_type not of type TransactionType")

        if instrument is None:
            raise TypeError("Required parameter instrument not of type Instrument")

        if not isinstance(quantity, int):
            raise TypeError("Required parameter quantity not of type int")

        if order_type is None:
            raise TypeError("Required parameter order_type not of type OrderType")

        if product_type is None:
            raise TypeError("Required parameter product_type not of type ProductType")

        if price is not None and not isinstance(price, float):
            raise TypeError("Optional parameter price not of type float")

        if trigger_price is not None and not isinstance(trigger_price, float):
            raise TypeError("Optional parameter trigger_price not of type float")
        if is_amo:
            complexty = "AMO"
        else:
            complexty = "regular"
        discqty = 0
        exch = instrument.exchange
        if (instrument.exchange == "NFO" or instrument.exchange == "MCX") and (
            product_type.value == "CNC"
        ):
            pCode = "NRML"
        else:
            if product_type.value == "BO":
                pCode = "MIS"
                complexty = "BO"
            else:
                pCode = product_type.value
        price = price
        prctyp = order_type.value
        qty = quantity
        if is_ioc:
            ret = "IOC"
        else:
            ret = "DAY"
        trading_symbol = instrument.name
        symbol_id = str(instrument.token)
        transtype = transaction_type.value
        trigPrice = trigger_price
        # print("pCode:",instrument)
        data = [
            {
                "complexty": complexty,
                "discqty": discqty,
                "exch": exch,
                "pCode": pCode,
                "price": price,
                "prctyp": prctyp,
                "qty": qty,
                "ret": ret,
                "symbol_id": symbol_id,
                "trading_symbol": trading_symbol,
                "transtype": transtype,
                "stopLoss": stop_loss,
                "target": square_off,
                "trailing_stop_loss": trailing_sl,
                "trigPrice": trigPrice,
                "orderTag": order_tag,
            }
        ]
        # print(data)
        placeorderresp = await self._post("placeorder", data)
        if len(placeorderresp) == 1:
            return placeorderresp[0]
        else:
            return placeorderresp

    """Method to get Funds Data"""

    async def get_balance(self):
        fundsresp = await self._get("fundsrecord")
        return fundsresp

    async def get_order_history(self, nextorder):
        orderresp = await self._get("orderbook")
        if nextorder == "":
            # orderresp = self._get("orderbook")
            return orderresp
        else:
            # data = {'nestOrderNumber': nextorder}
            # orderhistoryresp = self._post("orderhistory", data)
            # return orderhistoryresp
            for order in orderresp:
                if order["Nstordno"] == nextorder:
                    return order

    """Userlogin method with userid and userapi_key"""

    async def get_session_id(self, data=None):
        data = {"userId": self.user_id.upper()}
        response = await self._post("encryption_key", data)
        if response["encKey"] is None:
            return response
        else:
            data = encrypt_string(self.user_id.upper() + self.api_key + response["encKey"])
        data = {"userId": self.user_id.upper(), "userData": data}
        res = self._post("getsessiondata", data)

        if res["stat"] == "Ok":
            self.session_id = res["sessionID"]
        return res

    """GET Market watchlist"""

    async def getmarketwatch_list(self):
        marketwatchrespdata = await self._get("getmarketwatch_list")
        return marketwatchrespdata

    """GET Tradebook Records"""

    async def get_trade_book(self):
        tradebookresp = await self._get("tradebook")
        return tradebookresp

    async def get_profile(self):
        profile = await self._get("profile")
        return profile

    """GET Holdings Records"""

    async def get_holding_positions(self):
        holdingresp = await self._get("holding")
        return holdingresp

    """GET Orderbook Records"""

    async def order_data(self):
        orderresp = await self._get("orderbook")
        return orderresp

    """Method to call Cancel Orders"""

    async def cancel_order(self, nestordernmbr):
        data = {"nestOrderNumber": nestordernmbr}
        cancelresp = await self._post("cancelorder", data)
        return cancelresp

    """Method to call Squareoff Positions"""

    async def squareoff_positions(self, exchange, pCode, qty, tokenno, symbol):
        data = {
            "exchSeg": exchange,
            "pCode": pCode,
            "netQty": qty,
            "tockenNo": tokenno,
            "symbol": symbol,
        }
        squareoffresp = await self._post("squareoffposition", data)
        return squareoffresp

    """Method to call Modify Order"""

    async def modify_order(
        self,
        transaction_type,
        instrument,
        product_type,
        order_id,
        order_type,
        quantity,
        price=0.0,
        trigger_price=0.0,
    ):
        if not isinstance(instrument, Instrument):
            raise TypeError("Required parameter instrument not of type Instrument")

        if not isinstance(order_id, str):
            raise TypeError("Required parameter order_id not of type str")

        if not isinstance(quantity, int):
            raise TypeError("Optional parameter quantity not of type int")

        if type(order_type) is not OrderType:
            raise TypeError("Optional parameter order_type not of type OrderType")

        if ProductType is None:
            raise TypeError("Required parameter product_type not of type ProductType")

        if price is not None and not isinstance(price, float):
            raise TypeError("Optional parameter price not of type float")

        if trigger_price is not None and not isinstance(trigger_price, float):
            raise TypeError("Optional parameter trigger_price not of type float")
        data = {
            "discqty": 0,
            "exch": instrument.exchange,
            # 'filledQuantity': filledQuantity,
            "nestOrderNumber": order_id,
            "prctyp": order_type.value,
            "price": price,
            "qty": quantity,
            "trading_symbol": instrument.name,
            "trigPrice": trigger_price,
            "transtype": transaction_type.value,
            "pCode": product_type.value,
        }
        # print(data)
        modifyorderresp = await self._post("modifyorder", data)
        return modifyorderresp

    """Method to call Exitbook  Order"""

    async def exitboorder(
        self,
        nestOrderNumber,
        symbolOrderId,
        status,
    ):
        data = {
            "nestOrderNumber": nestOrderNumber,
            "symbolOrderId": symbolOrderId,
            "status": status,
        }
        exitboorderresp = await self._post("exitboorder", data)
        return exitboorderresp

    """Method to get Position Book"""

    async def positionbook(
        self,
        ret,
    ):
        data = {
            "ret": ret,
        }
        positionbookresp = await self._post("positiondata", data)
        return positionbookresp

    async def get_daywise_positions(self):
        data = {"ret": "DAY"}
        positionbookresp = await self._post("positiondata", data)
        return positionbookresp

    async def get_netwise_positions(
        self,
    ):
        data = {"ret": "NET"}
        positionbookresp = await self._post("positiondata", data)
        return positionbookresp

    async def place_basket_order(self, orders):
        data = []
        for i in range(len(orders)):
            order_data = orders[i]
            if "is_amo" in order_data and order_data["is_amo"]:
                complexty = "AMO"
            else:
                complexty = "regular"
            discqty = 0
            exch = order_data["instrument"].exchange
            if (
                order_data["instrument"].exchange == "NFO"
                and order_data["product_type"].value == "CNC"
            ):
                pCode = "NRML"
            else:
                pCode = order_data["product_type"].value
            price = order_data["price"] if "price" in order_data else 0

            prctyp = order_data["order_type"].value
            qty = order_data["quantity"]
            if "is_ioc" in order_data and order_data["is_ioc"]:
                ret = "IOC"
            else:
                ret = "DAY"
            trading_symbol = order_data["instrument"].name
            symbol_id = str(order_data["instrument"].token)
            transtype = order_data["transaction_type"].value
            trigPrice = order_data["trigger_price"] if "trigger_price" in order_data else None
            stop_loss = order_data["stop_loss"] if "stop_loss" in order_data else None
            trailing_sl = order_data["trailing_sl"] if "trailing_sl" in order_data else None
            square_off = order_data["square_off"] if "square_off" in order_data else None
            ordertag = order_data["order_tag"] if "order_tag" in order_data else None
            request_data = {
                "complexty": complexty,
                "discqty": discqty,
                "exch": exch,
                "pCode": pCode,
                "price": price,
                "prctyp": prctyp,
                "qty": qty,
                "ret": ret,
                "symbol_id": symbol_id,
                "trading_symbol": trading_symbol,
                "transtype": transtype,
                "stopLoss": stop_loss,
                "target": square_off,
                "trailing_stop_loss": trailing_sl,
                "trigPrice": trigPrice,
                "orderTag": ordertag,
            }
            data.append(request_data)
        # print(data)
        placeorderresp = await self._post("placeorder", data)
        return placeorderresp

    @staticmethod
    async def get_instrument_for_fno_from_redis(
        async_redis_client,
        symbol,
        expiry_date: datetime.date,
        is_fut=True,
        strike=None,
        is_CE=False,
    ):
        """
        instrument_ins_name: full name of the instrument
            For Ex: BANKNIFTY 12MAY23 43000 CE
        """
        if not is_fut and strike is None:
            raise ValueError("strike price is required for options")

        if is_fut:
            key = f"{symbol} {expiry_date.strftime(ALICE_BLUE_DATE_FORMAT).upper()} {FUT}"
        else:
            # TODO: remove conversion of strik to float when in redis we start storing strike as float
            key = f"{symbol} {expiry_date.strftime(ALICE_BLUE_DATE_FORMAT).upper()} {int(strike)} {OptionType.CE if is_CE else OptionType.PE}"

        instrument_json = await async_redis_client.get(key)
        result = json.loads(instrument_json or "{}")
        if result:
            return Instrument(
                result["Exch"],
                result["Token"],
                result["Symbol"],
                result["Trading Symbol"],
                result["Expiry Date"],
                result["Lot Size"],
            )
        else:
            return None

    # def get_all_instruments_for_fno(
    #     self,
    #     exch,
    #     symbol,
    #     expiry_date,
    #     current_month_expiry=None,
    # ):
    #     # print(exch)
    #     if exch in ["NFO", "CDS", "MCX", "BFO", "BCD"]:
    #         if exch == "CDS":
    #             edate_format = "%d-%m-%Y"
    #         else:
    #             edate_format = "%Y-%m-%d"
    #     else:
    #         return self._error_response("Invalid exchange")
    #     if not symbol:
    #         return self._error_response("Symbol is Null")
    #     try:
    #         expiry_date = datetime.strptime(expiry_date, "%Y-%m-%d").date()
    #     except ValueError as e:
    #         return self._error_response(e)
    #
    #     data_stream = io.StringIO(get_master_contract_content_from_s3())
    #     contract = pd.read_csv(data_stream)
    #
    #     # below filters out both futures and options
    #     filter_contract = contract[
    #         (contract["Exch"] == exch)
    #         & ((contract["Symbol"] == symbol) | (contract["Trading Symbol"] == symbol))
    #         & (contract["Expiry Date"] == expiry_date.strftime(edate_format))
    #         | (
    #             (contract["Option Type"] == "XX")
    #             & (contract["Expiry Date"] == current_month_expiry.strftime(edate_format))
    #         )
    #         & ((contract["Symbol"] == symbol) | (contract["Trading Symbol"] == symbol))
    #     ]
    #
    #     # print(len(filter_contract))
    #     if len(filter_contract) == 0:
    #         return self._error_response("No Data")
    #     else:
    #         inst = []
    #         token_lst = []
    #         token_full_name_dict = {}
    #         filter_contract = filter_contract.reset_index()
    #         for i in range(len(filter_contract)):
    #             if filter_contract["Token"][i] not in token_lst:
    #                 token = filter_contract["Token"][i]
    #                 exch = filter_contract["Exch"][i]
    #                 symbol = filter_contract["Symbol"][i]
    #                 trading_symbol = filter_contract["Trading Symbol"][i]
    #                 expiry_date = filter_contract["Expiry Date"][i]
    #                 lot_size = filter_contract["Lot Size"][i]
    #                 strike_price = filter_contract["Strike Price"][i]
    #                 option_type = filter_contract["Option Type"][i]
    #
    #                 token_lst.append(token)
    #                 if int(strike_price) == -1:
    #                     strike_price = "FUT"
    #
    #                 token_full_name_dict[
    #                     str(token)
    #                 ] = f"{symbol} {expiry_date} {strike_price} {option_type}"
    #                 inst.append(
    #                     Instrument(exch, token, symbol, trading_symbol, expiry_date, lot_size)
    #                 )
    #
    #         return inst, token_full_name_dict


async def get_pya3_obj(async_redis_client, broker_id, async_httpx_client) -> Pya3Aliceblue:
    broker_json = await async_redis_client.get(broker_id)

    if broker_json:
        broker_schema = BrokerSchema.parse_raw(broker_json)
    else:
        async with db():
            # We have a cron that update session token every 1 hour,
            # but frequency can be brought down to 1 day, but we dont know when it expires
            # but due to some reason it doesnt work then get session token updated using get_alice_blue_obj
            # and then create pya3_obj again and we would need to do it in place_order

            # TODO: fetch it from redis
            fetch_broker_query = await db.session.execute(
                select(BrokerModel).filter_by(id=str(broker_id))
            )
            broker_model = fetch_broker_query.scalars().one_or_none()

            if not broker_model:
                raise HTTPException(status_code=404, detail=f"Broker: {broker_id} not found")
            broker_schema = BrokerSchema.from_orm(broker_model)
            await async_redis_client.set(broker_id, broker_schema.json())

    # TODO: update cron updating alice blue access token to update redis as well with the latest access token
    pya3_obj = Pya3Aliceblue(
        user_id=broker_schema.username,
        api_key=broker_schema.api_key,
        session_id=broker_schema.access_token,
        async_httpx_client=async_httpx_client,
    )
    return pya3_obj


async def buy_alice_blue_trades(
    *,
    strike: float,
    signal_payload_schema: SignalPayloadSchema,
    strategy_schema: StrategySchema,
    async_redis_client: Redis,
    async_httpx_client: AsyncClient,
):
    """
    assumptions
        all trades to be executed should follow the below constraint:
            they all should hve SAME paramters as below:
            symbol [ for ex: either BANKNIFTY, NIFTY ]
            expiry
            call type [ for ex: either CE, PE ]
            nfo type [ for ex: either future or option]
    """

    pya3_obj = await get_pya3_obj(
        async_redis_client, str(strategy_schema.broker_id), async_httpx_client
    )

    strike, order_id = await place_ablue_order(
        pya3_obj=pya3_obj,
        strategy_schema=strategy_schema,
        async_redis_client=async_redis_client,
        strike=strike,
        quantity=signal_payload_schema.quantity,
        expiry=signal_payload_schema.expiry,
        is_CE=signal_payload_schema.option_type == OptionType.CE,
        is_buy=True,
    )

    for _ in range(40):
        latest_order_status = await pya3_obj.get_order_history(order_id)
        if latest_order_status["Status"] == Status.COMPLETE:
            return latest_order_status["Avgprc"]
        elif latest_order_status["Status"] == Status.REJECTED:
            # TODO: send whatsapp message using Twilio API instead of Telegram
            # Rejection Reason: latest_order_status["RejReason"]
            log.error(f"order_status: {latest_order_status}")
            raise HTTPException(status_code=403, detail=latest_order_status["RejReason"])
        else:
            log.warning(f"order_history: {latest_order_status}")
            await asyncio.sleep(0.5)


def get_exiting_trades_insights(redis_trade_schema_list: list[RedisTradeSchema]):
    strike_quantity_dict = defaultdict(int)

    for redis_trade_schema in redis_trade_schema_list:
        strike_quantity_dict[redis_trade_schema.strike] += redis_trade_schema.quantity

    if len(strike_quantity_dict):
        # even though loop is over, we still have the access to the last element
        return strike_quantity_dict, redis_trade_schema.expiry, redis_trade_schema.option_type


async def place_ablue_order(
    *,
    pya3_obj: Pya3Aliceblue,
    strategy_schema: StrategySchema,
    async_redis_client: Redis,
    strike: float,
    quantity: int,
    expiry: datetime.date,
    is_CE: bool,
    is_buy: bool,
):
    instrument = await pya3_obj.get_instrument_for_fno_from_redis(
        async_redis_client=async_redis_client,
        symbol=strategy_schema.symbol,
        expiry_date=expiry,
        is_fut=strategy_schema.instrument_type == InstrumentTypeEnum.FUTIDX,
        strike=strike,
        is_CE=is_CE,
    )

    place_order_response = await pya3_obj.place_order(
        transaction_type=TransactionType.Buy if is_buy else TransactionType.Sell,
        instrument=instrument,
        quantity=quantity,
        order_type=OrderType.Market,
        product_type=ProductType.Delivery,
    )

    if place_order_response["stat"] == "Not_ok":
        # TODO: try to refresh access token
        # TODO: update db with new access token
        # TODO: update redis with new access token
        raise HTTPException(status_code=403, detail=place_order_response["emsg"])

    # TODO: handle any error like what if we dont have NOrdNo in response
    return strike, place_order_response["NOrdNo"]


async def close_alice_blue_trades(
    redis_trade_schema_list: list[RedisTradeSchema],
    strategy_schema: StrategySchema,
    async_redis_client: Redis,
    async_httpx_client: AsyncClient,
):
    """
    assumptions
     all trades to be executed should belong to same:
      symbol [ for ex: either BANKNIFTY, NIFTY ]
      expiry
      call type [ for ex: either CE, PE ]
      nfo type [ for ex: either future or option]
    """

    strike_quantity_dict, expiry, option_type = get_exiting_trades_insights(
        redis_trade_schema_list
    )

    pya3_obj = await get_pya3_obj(
        async_redis_client, str(strategy_schema.broker_id), async_httpx_client
    )

    tasks = []
    for strike, quantity in strike_quantity_dict.items():
        tasks.append(
            asyncio.create_task(
                place_ablue_order(
                    pya3_obj=pya3_obj,
                    async_redis_client=async_redis_client,
                    strategy_schema=strategy_schema,
                    strike=strike,
                    quantity=quantity,
                    expiry=expiry,
                    is_CE=option_type == OptionType.CE,
                    is_buy=False,
                )
            )
        )

    if tasks:
        place_order_results = await asyncio.gather(*tasks)
        strike_exitprice_dict = {}
        for strike, order_id in place_order_results:
            order_history = await pya3_obj.get_order_history(order_id)
            for _ in range(20):
                if order_history["Status"] == Status.COMPLETE:
                    strike_exitprice_dict[strike] = order_history["Avgprc"]
                    break
                await asyncio.sleep(0.2)
            else:
                log.error(f"Unable to close strike: {strike}, order_history: {order_history}")

        return strike_exitprice_dict
