import asyncio
import json
import logging
from pprint import pprint

import httpx
from oandapyV20 import V20Error
from oandapyV20.contrib.requests import MarketOrderRequest
from oandapyV20.endpoints.orders import OrderCreate


ITER_LINES_CHUNKSIZE = 60

TRADING_ENVIRONMENTS = {
    "practice": {
        "stream": "https://stream-fxpractice.oanda.com",
        "api": "https://api-fxpractice.oanda.com",
    },
    "live": {
        "stream": "https://stream-fxtrade.oanda.com",
        "api": "https://api-fxtrade.oanda.com",
    },
}

DEFAULT_HEADERS = {"Accept-Encoding": "gzip, deflate"}

logger = logging.getLogger(__name__)


class AsyncAPI:
    def __init__(self, access_token, environment="practice", headers=None, request_params=None):
        self.environment = environment
        self.access_token = access_token
        self.client = httpx.AsyncClient()
        self.client.stream = False
        self._request_params = request_params if request_params else {}
        if self.access_token:
            self.client.headers["Authorization"] = "Bearer " + self.access_token
        self.client.headers.update(DEFAULT_HEADERS)
        if headers:
            self.client.headers.update(headers)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        await self.client.aclose()

    async def _make_request(self, method, url, request_args, headers=None, stream=False):
        headers = headers if headers else {}
        response = await getattr(self.client, method)(url, headers=headers, **request_args)
        if response.status_code >= 400:
            raise V20Error(response.status_code, response.content.decode())
        return response

    async def _make_stream_request(self, method, url, data=None, params=None, headers=None):
        async with self.client.stream(
            method, url, headers=headers, params=params, json=data
        ) as response:
            if response.status_code >= 400:
                raise V20Error(response.status_code, await response.text())
            async for line in response.aiter_lines():
                if line:
                    data = json.loads(line)
                    yield data

    async def request(self, endpoint):
        method = endpoint.method.lower()
        params = getattr(endpoint, "params", {})
        headers = getattr(endpoint, "HEADERS", {})
        data = getattr(endpoint, "data", None)

        request_args = {"params": params} if method == "get" else {"json": data}
        request_args.update(self._request_params)
        endpoint_type = getattr(endpoint, "STREAM", "REST")
        api_url_key = "api" if endpoint_type != "STREAM" else "stream"
        url = "{}/{}".format(TRADING_ENVIRONMENTS[self.environment][api_url_key], endpoint)

        if endpoint_type == "STREAM":
            endpoint.response = self._make_stream_request(
                method, url, **request_args, headers=headers
            )
        else:
            response = await self._make_request(method, url, request_args, headers=headers)
            content = response.json()
            endpoint.response = content
            endpoint.status_code = response.status_code
            return content


if __name__ == "__main__":
    access_token = "c1a1da5b257e3eb61082d88d6c41108d-3c1a484c1cf2b8ee215bef4e36807aad"
    account_id = "101-004-28132533-001"
    client = AsyncAPI(access_token=access_token)
    market_order_request = MarketOrderRequest(instrument="EUR_USD", units=1000)
    response = asyncio.run(
        client.request(OrderCreate(account_id, data=market_order_request.data))
    )
    pprint(response)
