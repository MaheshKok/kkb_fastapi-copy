import asyncio
import logging
import re
import socket
import ssl
import uuid
from urllib.parse import urljoin

import httpx
from SmartApi.version import __title__
from SmartApi.version import __version__


class AsyncSmartConnect:
    # _rootUrl = "https://openapisuat.angelbroking.com"
    _rootUrl = "https://apiconnect.angelbroking.com"  # prod endpoint
    # _login_url ="https://smartapi.angelbroking.com/login"
    _login_url = "https://smartapi.angelbroking.com/publisher-login"  # prod endpoint
    _default_timeout = 7  # In seconds

    _routes = {
        "api.login": "/rest/auth/angelbroking/user/v1/loginByPassword",
        "api.logout": "/rest/secure/angelbroking/user/v1/logout",
        "api.token": "/rest/auth/angelbroking/jwt/v1/generateTokens",
        "api.refresh": "/rest/auth/angelbroking/jwt/v1/generateTokens",
        "api.user.profile": "/rest/secure/angelbroking/user/v1/getProfile",
        "api.order.place": "/rest/secure/angelbroking/order/v1/placeOrder",
        "api.order.placefullresponse": "/rest/secure/angelbroking/order/v1/placeOrder",
        "api.order.modify": "/rest/secure/angelbroking/order/v1/modifyOrder",
        "api.order.cancel": "/rest/secure/angelbroking/order/v1/cancelOrder",
        "api.order.book": "/rest/secure/angelbroking/order/v1/getOrderBook",
        "api.ltp.data": "/rest/secure/angelbroking/order/v1/getLtpData",
        "api.trade.book": "/rest/secure/angelbroking/order/v1/getTradeBook",
        "api.rms.limit": "/rest/secure/angelbroking/user/v1/getRMS",
        "api.holding": "/rest/secure/angelbroking/portfolio/v1/getHolding",
        "api.position": "/rest/secure/angelbroking/order/v1/getPosition",
        "api.convert.position": "/rest/secure/angelbroking/order/v1/convertPosition",
        "api.gtt.create": "/gtt-service/rest/secure/angelbroking/gtt/v1/createRule",
        "api.gtt.modify": "/gtt-service/rest/secure/angelbroking/gtt/v1/modifyRule",
        "api.gtt.cancel": "/gtt-service/rest/secure/angelbroking/gtt/v1/cancelRule",
        "api.gtt.details": "/rest/secure/angelbroking/gtt/v1/ruleDetails",
        "api.gtt.list": "/rest/secure/angelbroking/gtt/v1/ruleList",
        "api.candle.data": "/rest/secure/angelbroking/historical/v1/getCandleData",
        "api.market.data": "/rest/secure/angelbroking/market/v1/quote",
        "api.search.scrip": "/rest/secure/angelbroking/order/v1/searchScrip",
        "api.allholding": "/rest/secure/angelbroking/portfolio/v1/getAllHolding",
        "api.individual.order.details": "/rest/secure/angelbroking/order/v1/details/",
        "api.margin.api": "rest/secure/angelbroking/margin/v1/batch",
    }

    try:
        clientPublicIp = " " + httpx.get("https://api.ipify.org").text
        if " " in clientPublicIp:
            clientPublicIp = clientPublicIp.replace(" ", "")
        hostname = socket.gethostname()
        clientLocalIp = socket.gethostbyname(hostname)
    except Exception as e:
        logging.error(f"Exception while retriving IP Address,using local host IP address: {e}")
    finally:
        clientPublicIp = "106.193.147.98"
        clientLocalIp = "127.0.0.1"
    clientMacAddress = ":".join(re.findall("..", "%012x" % uuid.getnode()))
    accept = "application/json"
    userType = "USER"
    sourceID = "WEB"

    def __init__(
        self,
        api_key=None,
        access_token=None,
        refresh_token=None,
        feed_token=None,
        user_id=None,
        root=None,
        debug=False,
        timeout=None,
        proxies=None,
        disable_ssl=False,
    ):
        self.debug = debug
        self.api_key = api_key
        self.session_expiry_hook = None
        self.disable_ssl = disable_ssl
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.feed_token = feed_token
        self.user_id = user_id
        self.proxies = proxies if proxies else {}
        self.root = root or self._rootUrl
        self.timeout = timeout or self._default_timeout
        self.Authorization = None
        self.clientLocalIP = self.clientLocalIp
        self.clientPublicIP = self.clientPublicIp
        self.clientMacAddress = self.clientMacAddress
        self.privateKey = api_key
        self.accept = self.accept
        self.userType = self.userType
        self.sourceID = self.sourceID

        # Create SSL context
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.options |= ssl.OP_NO_TLSv1  # Disable TLS 1.0
        self.ssl_context.options |= ssl.OP_NO_TLSv1_1  # Disable TLS 1.1

        # Configure minimum TLS version to TLS 1.2
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

    def request_headers(self):
        return {
            "Content-type": self.accept,
            "X-ClientLocalIP": self.clientLocalIp,
            "X-ClientPublicIP": self.clientPublicIp,
            "X-MACAddress": self.clientMacAddress,
            "Accept": self.accept,
            "X-PrivateKey": self.privateKey,
            "X-UserType": self.userType,
            "X-SourceID": self.sourceID,
        }

    def get_user_id(self):
        return self.user_id

    def set_user_id(self, user_id):
        self.user_id = user_id

    def set_access_token(self, access_token):
        self.access_token = access_token

    def set_refresh_token(self, refresh_token):
        self.refresh_token = refresh_token

    def set_feed_token(self, feed_token):
        self.feed_token = feed_token

    def getfeed_token(self):
        return self.feed_token

    def login_url(self):
        """Get the remote login url to which a user should be redirected to initiate the login flow."""
        return "%s?api_key=%s" % (self._login_url, self.api_key)

    async def _request(self, method, route, params=None, retries=None, backoff_factor=1):
        """
        An asynchronous method to make HTTP requests with retry logic for handling 429 status codes.
        """
        params = params.copy() if params else {}
        uri = self._routes[route].format(**params)

        url = urljoin(self.root, uri)
        # Custom headers
        headers = self.request_headers()

        if self.access_token:
            # set authorization header

            auth_header = self.access_token
            headers["Authorization"] = "Bearer {}".format(auth_header)

        async with httpx.AsyncClient() as client:
            for attempt in range(retries or 10):
                response = await client.request(
                    method,
                    url,
                    params=params if method in ["GET", "DELETE"] else None,
                    json=params if method in ["POST", "PUT"] else None,
                    headers=headers,
                )

                if response.status_code == 429:  # Too Many Requests
                    retry_after = int(
                        response.headers.get("Retry-After", backoff_factor * (2**attempt))
                    )
                    await asyncio.sleep(retry_after)
                    continue  # Retry the request

                if response.status_code == 403:  # Too Many Requests\
                    retry_after = int(
                        response.headers.get("Retry-After", backoff_factor * (2**attempt))
                    )
                    logging.warning(f"retrying for : {attempt} after : {retry_after}")
                    await asyncio.sleep(retry_after)
                    continue  # Retry the request
                response.raise_for_status()  # Raises an exception for 4XX/5XX status codes
                return response.json()

            # If all retries fail, raise the last received HTTP error
            response.raise_for_status()

    async def _get_request(self, route, params=None, retries=3, backoff_factor=1):
        """
        Perform a GET request.
        """
        return await self._request("GET", route, params, retries, backoff_factor)

    async def _post_request(self, route, params=None, retries=3, backoff_factor=1):
        """
        Perform a POST request.
        """
        return await self._request("POST", route, params, retries, backoff_factor)

    async def _delete_request(self, route, params=None, retries=3, backoff_factor=1):
        """Alias for sending a DELETE request."""
        return await self._request("DELETE", route, params, retries, backoff_factor)

    async def _put_request(self, route, params=None, retries=3, backoff_factor=1):
        """Alias for sending a PUT request."""
        return self._request("PUT", route, params, retries, backoff_factor)

    async def get_profile(self, refresh_token):
        user = await self._get_request("api.user.profile", {"refreshToken": refresh_token})
        return user

    async def generate_session(self, client_code, password, totp):
        params = {"clientcode": client_code, "password": password, "totp": totp}
        login_result_object = await self._post_request("api.login", params)

        if login_result_object["status"]:
            jwt_token = login_result_object["data"]["jwtToken"]
            self.set_access_token(jwt_token)
            refresh_token = login_result_object["data"]["refreshToken"]
            feed_token = login_result_object["data"]["feedToken"]
            self.set_refresh_token(refresh_token)
            self.set_feed_token(feed_token)
            user = await self.get_profile(refresh_token)

            _id = user["data"]["clientcode"]
            # id='D88311'
            self.set_user_id(_id)
            user["data"]["jwtToken"] = "Bearer " + jwt_token
            user["data"]["refreshToken"] = refresh_token
            user["data"]["feedToken"] = feed_token

            return user
        else:
            return login_result_object

    async def terminate_session(self, client_code):
        logout_response_object = await self._post_request(
            "api.logout", {"clientcode": client_code}
        )
        return logout_response_object

    async def generate_token(self, refresh_token):
        response = await self._post_request("api.token", {"refreshToken": refresh_token})
        jwt_token = response["data"]["jwtToken"]
        feed_token = response["data"]["feedToken"]
        self.set_feed_token(feed_token)
        self.set_access_token(jwt_token)

        return response

    async def renew_access_token(self):
        response = await self._post_request(
            "api.refresh",
            {
                "jwtToken": self.access_token,
                "refreshToken": self.refresh_token,
            },
        )

        token_set = {}

        if "jwtToken" in response:
            token_set["jwtToken"] = response["data"]["jwtToken"]
        token_set["clientcode"] = self.user_id
        token_set["refreshToken"] = response["data"]["refreshToken"]

        return token_set

    async def get_margin_api(self, params):
        margin_api_result = await self._post_request("api.margin.api", params)
        return margin_api_result

    @staticmethod
    def _user_agent():
        return (__title__ + "-python/").capitalize() + __version__

    async def place_order(self, orderparams):
        params = orderparams
        for k in list(params.keys()):
            if params[k] is None:
                del params[k]
        response = await self._post_request("api.order.place", params)
        if response is not None and response.get("status", False):
            if (
                "data" in response
                and response["data"] is not None
                and "orderid" in response["data"]
            ):
                order_response = response["data"]["orderid"]
                return order_response
            else:
                logging.error(f"Invalid response format: {response}")
        else:
            logging.error(f"API request failed: {response}")
        return None

    async def place_order_full_response(self, orderparams):
        params = orderparams
        for k in list(params.keys()):
            if params[k] is None:
                del params[k]
        response = await self._post_request("api.order.placefullresponse", params)
        if response is not None and response.get("status", False):
            if (
                "data" in response
                and response["data"] is not None
                and "orderid" in response["data"]
            ):
                order_response = response
                return order_response
            else:
                logging.error(f"Invalid response format: {response}")
        else:
            logging.error(f"API request failed: {response}")
        return None

    async def modify_order(self, orderparams):
        params = orderparams
        for k in list(params.keys()):
            if params[k] is None:
                del params[k]
        order_response = await self._post_request("api.order.modify", params)
        return order_response

    async def cancel_order(self, order_id, variety):
        order_response = await self._post_request(
            "api.order.cancel", {"variety": variety, "orderid": order_id}
        )
        return order_response

    async def ltp_data(self, exchange, tradingsymbol, symboltoken):
        params = {
            "exchange": exchange,
            "tradingsymbol": tradingsymbol,
            "symboltoken": symboltoken,
        }
        ltp_data_response = await self._post_request("api.ltp.data", params)
        return ltp_data_response

    async def order_book(self):
        order_book_response = await self._get_request("api.order.book")
        return order_book_response

    async def trade_book(self):
        trade_book_response = await self._get_request("api.trade.book")
        return trade_book_response

    async def rms_limit(self):
        rms_limit_response = await self._get_request("api.rms.limit")
        return rms_limit_response

    async def position(self):
        position_response = await self._get_request("api.position")
        return position_response

    async def holding(self):
        holding_response = await self._get_request("api.holding")
        return holding_response

    async def all_holding(self):
        all_holding_response = await self._get_request("api.allholding")
        return all_holding_response

    async def convert_position(self, position_params):
        params = position_params
        for k in list(params.keys()):
            if params[k] is None:
                del params[k]
        convert_position_response = await self._post_request("api.convert.position", params)
        return convert_position_response

    async def gtt_create_rule(self, create_rule_params):
        params = create_rule_params
        for k in list(params.keys()):
            if params[k] is None:
                del params[k]
        create_gtt_rule_response = await self._post_request("api.gtt.create", params)
        return create_gtt_rule_response["data"]["id"]

    async def gtt_modify_rule(self, modify_rule_params):
        params = modify_rule_params
        for k in list(params.keys()):
            if params[k] is None:
                del params[k]
        modify_gtt_rule_response = await self._post_request("api.gtt.modify", params)
        return modify_gtt_rule_response["data"]["id"]

    async def gtt_cancel_rule(self, gtt_cancel_params):
        params = gtt_cancel_params
        for k in list(params.keys()):
            if params[k] is None:
                del params[k]
        cancel_gtt_rule_response = await self._post_request("api.gtt.cancel", params)
        return cancel_gtt_rule_response

    async def gtt_details(self, gtt_id):
        params = {"id": gtt_id}
        gtt_details_response = await self._post_request("api.gtt.details", params)
        return gtt_details_response

    async def get_candle_data(self, historic_data_params):
        params = historic_data_params
        for k in list(params.keys()):
            if params[k] is None:
                del params[k]
        get_candle_data_response = await self._post_request(
            "api.candle.data", historic_data_params
        )
        return get_candle_data_response

    async def get_market_data(self, mode, exchange_token):
        params = {"mode": mode, "exchangeTokens": exchange_token}
        market_data_result = await self._post_request("api.market.data", params)
        return market_data_result

    async def search_scrip(self, exchange, search_scrip):
        params = {"exchange": exchange, "searchscrip": search_scrip}
        search_scrip_result = await self._post_request("api.search.scrip", params)
        if search_scrip_result["status"] is True and search_scrip_result["data"]:
            message = f"Search successful. Found {len(search_scrip_result['data'])} trading symbols for the given query:"
            symbols = ""
            for index, item in enumerate(search_scrip_result["data"], start=1):
                symbol_info = f"{index}. exchange: {item['exchange']}, tradingsymbol: {item['tradingsymbol']}, symboltoken: {item['symboltoken']}"
                symbols += "\n" + symbol_info
            logging.info(message + symbols)
            return search_scrip_result
        elif search_scrip_result["status"] is True and not search_scrip_result["data"]:
            logging.info(
                "Search successful. No matching trading symbols found for the given query."
            )
            return search_scrip_result
        else:
            return search_scrip_result

    async def make_authenticated_get_request(self, url, access_token):
        headers = self.request_headers()
        if access_token:
            headers["Authorization"] = "Bearer " + access_token

        async with httpx.AsyncClient() as client:
            for attempt in range(10):
                response = await client.request(
                    "GET",
                    url,
                    params=None,
                    json=None,
                    headers=headers,
                )

                if response.status_code == 429:  # Too Many Requests
                    retry_after = int(response.headers.get("Retry-After", 1 * (2**attempt)))
                    await asyncio.sleep(retry_after)
                    continue  # Retry the request

                if response.status_code == 403:  # Too Many Requests\
                    retry_after = int(response.headers.get("Retry-After", 1 * (2**attempt)))
                    logging.warning(f"retrying for : {attempt} after : {retry_after}")
                    await asyncio.sleep(retry_after)
                    continue  # Retry the request
                response.raise_for_status()  # Raises an exception for 4XX/5XX status codes
                return response.json()

            # If all retries fail, raise the last received HTTP error
            response.raise_for_status()

            if response.status_code == 200:
                return response.json()
            else:
                logging.error(f"Error in make_authenticated_get_request: {response.status_code}")
                return None

    async def individual_order_details(self, q_param):
        url = self._rootUrl + self._routes["api.individual.order.details"] + q_param
        try:
            response_data = await self.make_authenticated_get_request(url, self.access_token)
            return response_data
        except Exception as e:
            logging.error(f"Error occurred in ind_order_details: {e}")
            return None
