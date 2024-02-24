import asyncio
import base64
import datetime
import hashlib
import json
import logging
import os

import httpx
import pyotp
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import modes
from fastapi import HTTPException
from pya3 import Aliceblue
from pya3 import Instrument
from pya3 import OrderType
from pya3 import ProductType
from pya3 import encrypt_string

from app.schemas.trade import generate_trading_symbol
from app.utils.constants import OptionType


logging.basicConfig(level=logging.DEBUG)


class CryptoJsAES:
    @staticmethod
    def __pad(data):
        BLOCK_SIZE = 16
        length = BLOCK_SIZE - (len(data) % BLOCK_SIZE)
        return data + (chr(length) * length).encode()

    @staticmethod
    def __unpad(data):
        return data[: -(data[-1] if type(data[-1]) == int else ord(data[-1]))]

    @staticmethod
    def __bytes_to_key(data, salt, output=48):
        assert len(salt) == 8, len(salt)
        data += salt
        key = hashlib.md5(data).digest()
        final_key = key
        while len(final_key) < output:
            key = hashlib.md5(key + data).digest()
            final_key += key
        return final_key[:output]

    @staticmethod
    def encrypt(message, passphrase):
        salt = os.urandom(8)
        key_iv = CryptoJsAES.__bytes_to_key(passphrase, salt, 32 + 16)
        key = key_iv[:32]
        iv = key_iv[32:]
        aes = Cipher(algorithms.AES(key), modes.CBC(iv))
        return base64.b64encode(
            b"Salted__"
            + salt
            + aes.encryptor().update(CryptoJsAES.__pad(message))
            + aes.encryptor().finalize()
        )

    @staticmethod
    def decrypt(encrypted, passphrase):
        encrypted = base64.b64decode(encrypted)
        assert encrypted[0:8] == b"Salted__"
        salt = encrypted[8:16]
        key_iv = CryptoJsAES.__bytes_to_key(passphrase, salt, 32 + 16)
        key = key_iv[:32]
        iv = key_iv[32:]
        aes = Cipher(algorithms.AES(key), modes.CBC(iv))
        return CryptoJsAES.__unpad(
            aes.decryptor.update(encrypted[16:]) + aes.decryptor().finalize()
        )


class AsyncPya3Aliceblue(Aliceblue):
    host = "https://ant.aliceblueonline.com/rest/AliceBlueAPIService"

    _sub_urls = {
        "webLogin": f"{host}/customer/webLogin",
        "twoFA": f"{host}/sso/2fa",
        "sessionID": f"{host}/api/customer/getUserSID",
        "getEncKey": f"{host}/customer/getEncryptionKey",
        "verifyTotp": f"{host}/sso/verifyTotp",
        "getApiKey": f"{host}/api/getApiKey",
        "authorizeVendor": f"{host}/sso/authorizeVendor",
        "apiGetEncKey": f"{host}/api/customer/getAPIEncpkey",
        "profile": f"{host}/api/customer/accountDetails",
        "placeOrder": f"{host}/api/placeOrder/executePlaceOrder",
        "logout": f"{host}/api/customer/logout",
        "logoutFromAllDevices": f"{host}/api/customer/logOutFromAllDevice",
        "fetchMWList": f"{host}/api/marketWatch/fetchMWList",
        "fetchMWScrips": f"{host}/api/marketWatch/fetchMWScrips",
        "addScripToMW": f"{host}/api/marketWatch/addScripToMW",
        "deleteMWScrip": f"{host}/api/marketWatch/deleteMWScrip",
        "scripDetails": f"{host}/api/ScripDetails/getScripQuoteDetails",
        "positions": f"{host}/api/positionAndHoldings/positionBook",
        "holdings": f"{host}/api/positionAndHoldings/holdings",
        "sqrOfPosition": f"{host}/api/positionAndHoldings/sqrOofPosition",
        "fetchOrder": f"{host}/api/placeOrder/fetchOrderBook",
        "fetchTrade": f"{host}/api/placeOrder/fetchTradeBook",
        "exitBracketOrder": f"{host}/api/placeOrder/exitBracketOrder",
        "modifyOrder": f"{host}/api/placeOrder/modifyOrder",
        "cancelOrder": f"{host}/api/placeOrder/cancelOrder",
        "orderHistory": f"{host}/api/placeOrder/orderHistory",
        "getRmsLimits": f"{host}/api/limits/getRmsLimits",
        "createWsSession": f"{host}/api/ws/createSocketSess",
        "history": f"{host}/api/chart/history",
        "master_contract": "https://v2api.aliceblueonline.com/restpy/contract_master?exch={exchange}",
        "ws": "wss://ws1.aliceblueonline.com/NorenWS/",
        "getmargin": f"{host}/api/info/getmargin",
    }

    def __init__(
        self,
        *,
        user_id,
        password,
        api_key,
        async_httpx_client: httpx.AsyncClient,
        totp,
        twoFA,
        app_id,
        base=None,
        session_id=None,
        disable_ssl=False,
    ):
        super().__init__(user_id, api_key, base, session_id, disable_ssl)
        self.async_httpx_client = async_httpx_client
        self.password = password
        self.totp = totp
        self.twoFA = twoFA
        self.app_id = app_id
        self.api_key = api_key

    async def login_and_get_session_id(self):
        """Login and get Session ID"""
        header = {"Content-Type": "application/json"}
        # Get Encryption Key
        data = {"userId": self.user_id}
        get_enc_key_response = await self._post("getEncKey", data=data)

        if get_enc_key_response.get("stat") == "Not_Ok":
            logging.info(
                f"User: [ {self.user_id} ] - Error while retrieving Encryption Key: {get_enc_key_response}"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Error while retrieving Encryption Key: {get_enc_key_response}",
            )
        encKey = get_enc_key_response["encKey"]

        if not encKey:
            logging.info(
                f"User: [ {self.user_id} ] - Error while retrieving Encryption Key: {get_enc_key_response}"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Error while retrieving Encryption Key: {get_enc_key_response['emsg']}",
            )
        # Web Login
        checksum = CryptoJsAES.encrypt(self.password.encode(), encKey.encode())
        checksum = checksum.decode("utf-8")
        data = {"userId": self.user_id, "userData": checksum}
        await self._post("webLogin", data=data)

        # Web Login 2FA
        data = {
            "answer1": self.twoFA,
            "sCount": "1",
            "sIndex": "1",
            "userId": self.user_id,
            "vendor": self.app_id,
        }
        two_fa_response = await self._post("twoFA", data=data)
        try:
            auth_us = two_fa_response["us"]
            logging.info(f"User: [ {self.user_id} ] - Step 1 - Web Login 2FA successfull")
        except KeyError:
            msg = f"User: [ {self.user_id} ] - Step 1 - Error while Web Login 2FA, error: {two_fa_response}"
            logging.error(msg)
            raise HTTPException(status_code=400, detail=msg)

        # Web Login Totp
        totp = str(pyotp.TOTP(self.totp).now())
        data = {"userId": self.user_id, "tOtp": totp}
        header["Authorization"] = f"Bearer {self.user_id} {auth_us}"
        verify_totp_response = await self.async_httpx_client.post(
            self._sub_urls["verifyTotp"], data=json.dumps(data), headers=header
        )
        try:
            # Web Login Api Key
            userSessionID = verify_totp_response.json()["userSessionID"]
            logging.info(f"User: [ {self.user_id} ] - Step 2 - Web Login via Totp successfull")
        except KeyError:
            msg = f"User: [ {self.user_id} ] - Step 2 - Error while Web Login via Totp, error: {verify_totp_response.json()}"
            logging.error(msg)
            raise HTTPException(status_code=400, detail=msg)

        header["Authorization"] = f"Bearer {self.user_id} {userSessionID}"
        # Get API Encryption Key
        data = {"userId": self.user_id}
        api_enc_key_response = await self.async_httpx_client.post(
            self._sub_urls["apiGetEncKey"],
            headers=header,
            data=json.dumps(data),
        )
        try:
            encKey = api_enc_key_response.json()["encKey"]
            logging.info(
                f"User: [ {self.user_id} ] - Step 3 - Get API Encryption Key successfull"
            )
        except KeyError:
            msg = f"User: [ {self.user_id} ] - Step 3 - Error while Get API Encryption Key, error: {api_enc_key_response.json()}"
            logging.error(msg)
            raise HTTPException(status_code=400, detail=msg)

        # Get User Details/Session ID
        checksum = hashlib.sha256(f"{self.user_id}{self.api_key}{encKey}".encode()).hexdigest()
        data = {"userId": self.user_id, "userData": checksum}
        session_id_response = await self.async_httpx_client.post(
            self._sub_urls["sessionID"],
            headers=header,
            data=json.dumps(data),
        )
        try:
            session_id = session_id_response.json()["sessionID"]
            logging.info(f"User: [ {self.user_id} ] - Step 4 - Session ID successfull")
        except KeyError:
            msg = f"User: [ {self.user_id} ] - Step 4 - Error while retrieving Session ID, error: {session_id_response.json()}"
            logging.error(msg)
            raise HTTPException(status_code=400, detail=msg)

        return session_id

    async def _get(self, sub_url, data=None):
        """Get method declaration"""
        url = self._sub_urls[sub_url]
        response = await self._request(url, "GET", data=data)
        return response

    async def _post(self, sub_url, data=None):
        """Post method declaration"""
        url = self._sub_urls[sub_url]
        response = await self._request(url, "POST", data=data)
        return response

    async def _dummypost(self, url, data=None):
        """Post method declaration"""
        response = await self._request(url, "POST", data=data)
        return response

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
        placeorderresp = await self._post("placeOrder", data)
        if len(placeorderresp) == 1:
            return placeorderresp[0]
        else:
            return placeorderresp

    """Method to get Funds Data"""

    async def get_balance(self):
        fundsresp = await self._get("getRmsLimits")
        return fundsresp

    async def get_order_history(self, nextorder):
        orderresp = await self._get("fetchOrder")
        if nextorder == "":
            # orderresp = self._get("fetchOrder")
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
        response = await self._post("getEncKey", data)
        if response["encKey"] is None:
            return response
        else:
            data = encrypt_string(self.user_id.upper() + self.api_key + response["encKey"])
        data = {"userId": self.user_id.upper(), "userData": data}
        res = await self._post("sessionID", data)

        if res["stat"] == "Ok":
            self.session_id = res["sessionID"]
        return res

    """GET Market watchlist"""

    async def getmarketwatch_list(self):
        marketwatchrespdata = await self._get("fetchMWList")
        return marketwatchrespdata

    """GET Tradebook Records"""

    async def get_trade_book(self):
        tradebookresp = await self._get("fetchTradeBook")
        return tradebookresp

    async def get_profile(self):
        profile = await self._get("profile")
        return profile

    """GET Holdings Records"""

    async def get_holding_positions(self):
        holdingresp = await self._get("holdings")
        return holdingresp

    """GET Orderbook Records"""

    async def order_data(self):
        orderresp = await self._get("fetchOrder")
        return orderresp

    """Method to call Cancel Orders"""

    async def cancel_order(self, nestordernmbr):
        data = {"nestOrderNumber": nestordernmbr}
        cancelresp = await self._post("cancelOrder", data)
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
        squareoffresp = await self._post("sqrOofPosition", data)
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
        modifyorderresp = await self._post("modifyOrder", data)
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
        exitboorderresp = await self._post("exitBracketOrder", data)
        return exitboorderresp

    """Method to get Position Book"""

    async def positionbook(
        self,
        ret,
    ):
        data = {
            "ret": ret,
        }
        positionbookresp = await self._post("positions", data)
        return positionbookresp

    async def get_daywise_positions(self):
        data = {"ret": "DAY"}
        positionbookresp = await self._post("positions", data)
        return positionbookresp

    async def get_netwise_positions(
        self,
    ):
        data = {"ret": "NET"}
        positionbookresp = await self._post("positions", data)
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
        placeorderresp = await self._post("placeOrder", data)
        return placeorderresp

    async def get_margin(
        self,
        *,
        exchange: str,
        tradingSymbol,
        qty: float,
        product: str,
        priceType: str,
        price: str,
        token: str,
        transType: str,
    ):
        """
        example:
        payload = {
            "exchange": "NSE", (NSE or BSE or NFO or MCX)
            "tradingSymbol": "INFY-EQ",
            "price": "1475.20",
            "qty": "122",
            "product": "MIS", (MIS or CO or CNC or BO or NRML)
            "priceType": "L", (L or MKT or SL or SL-M)
            "token": "1594",
            "transType": "B", ("Buy" or "Sell")
        }
        """
        payload = {
            "exchange": exchange,
            "tradingSymbol": tradingSymbol,
            "price": price,
            "qty": qty,
            "product": product,
            "priceType": priceType,
            "token": token,
            # it means transaction type Buy or Sell
            "transType": transType,
        }
        response = await self._post("getMargin", payload)
        return response

    @staticmethod
    async def get_fno_instrument_from_redis(
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
            key = generate_trading_symbol(symbol=symbol, expiry=expiry_date, is_fut=True)
        else:
            key = generate_trading_symbol(
                symbol=symbol,
                expiry=expiry_date,
                option_type=OptionType.CE if is_CE else OptionType.PE,
                strike=strike,
            )

        instrument_json = await async_redis_client.get(key)
        result = json.loads(instrument_json or "{}")
        if result:
            return Instrument(
                result["Exch"],
                result["Token"],
                result["Symbol"],
                key,
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
