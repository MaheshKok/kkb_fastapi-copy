import json
from base64 import b64decode
from base64 import b64encode

import httpx
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA


class AsyncCapitalClient:
    def __init__(self, username, api_key, password, demo=False):
        self.username = username
        self.api_key = api_key
        self.password = password
        self.headers = {
            "X-CAP-API-KEY": self.api_key,
            "content-type": "application/json",
        }
        if demo is False:
            self.server = "https://api-capital.backend-capital.com"
        else:
            self.server = "https://demo-api-capital.backend-capital.com"

    async def __get_encryption_key__(self):
        url = f"{self.server}/api/v1/session/encryptionKey"
        response = await self.__make_request__("get", url)
        data = response.json()
        self.enc_key = [data["encryptionKey"], data["timeStamp"]]

    async def __make_request__(self, type, url, payload=None):
        async with httpx.AsyncClient() as client:
            if payload is None:
                payload = {}
            response = await client.request(type, url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response

    async def __encrypt__(self, password, key):
        key = b64decode(key)
        key = RSA.importKey(key)
        cipher = PKCS1_v1_5.new(key)
        ciphertext = b64encode(cipher.encrypt(bytes(password, "utf-8")))
        return ciphertext

    async def __create_session__(self):
        await self.__get_encryption_key__()
        url = f"{self.server}/api/v1/session"
        string_encrypt = f"{self.password}|{self.enc_key[1]}"
        encrypted_password = str(await self.__encrypt__(string_encrypt, self.enc_key[0]), "utf-8")
        payload = {
            "identifier": self.username,
            "password": encrypted_password,
            "encryptedPassword": True,
        }
        response = await self.__make_request__("post", url, payload)
        response_headers = response.headers
        self.CST = response_headers["CST"]
        self.X_TOKEN = response_headers["X-SECURITY-TOKEN"]
        self.headers.update(
            {
                "X-SECURITY-TOKEN": self.X_TOKEN,
                "CST": self.CST,
            }
        )

    async def __confirmation__(self, deal_reference):
        url = f"{self.server}/api/v1/confirms/{deal_reference}"
        response = await self.__make_request__("get", url, payload="")
        return response

    async def all_accounts(self):
        await self.__create_session__()
        url = f"{self.server}/api/v1/accounts"
        response = await self.__make_request__("get", url)
        await self.__log_out__()
        return response.json()

    async def account_pref(self):
        await self.__create_session__()
        url = f"{self.server}/api/v1/accounts/preferences"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

    async def update_account_pref(
        self,
        leverages=None,
        hedging_mode=False,
    ):
        await self.__create_session__()
        if not leverages:
            leverages = {
                "SHARES": 5,
                "INDICES": 20,
                "CRYPTOCURRENCIES": 2,
            }
        payload = {
            "leverages": leverages,
            "hedgingMode": hedging_mode,
        }
        url = f"{self.server}/api/v1/accounts/preferences"
        response = await self.__make_request__("put", url, payload=payload)
        await self.__log_out__()
        return response.json()

    async def get_account_activity(self):
        await self.__create_session__()
        url = f"{self.server}/api/v1/history/activity?lastPeriod=86400"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

        # get all profit, loss and overnight fees details

    async def get_transactions(self):
        await self.__create_session__()
        url = f"{self.server}/api/v1/history/transactions?lastPeriod=86400"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

    # Switch active account
    async def change_active_account(self, account_id):
        await self.__create_session__()
        url = f"{self.server}/api/v1/session"
        payload = json.dumps({"accountId": account_id})
        response = await self.__make_request__("put", url, payload=payload)
        await self.__log_out__()
        return response.json()

    # gets you all current positions
    async def all_positions(self):
        await self.__create_session__()
        url = f"{self.server}/api/v1/positions"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

    async def get_position(self, dealId):
        await self.__create_session__()
        url = f"{self.server}/api/v1/positions/{dealId}"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

    # Opens a new position
    async def create_position(
        self,
        epic,
        direction,
        size,
        guaranteed_stop=False,
        trailing_stop=False,
        stop_level=None,
        stop_distance=None,
        stop_amount=None,
        profit_level=None,
        profit_distance=None,
        profit_amount=None,
    ):
        await self.__create_session__()
        url = f"{self.server}/api/v1/positions"
        payload = {
            "epic": epic,
            "direction": direction.upper(),
            "size": str(size),
            "guaranteedStop": guaranteed_stop,
            "trailingStop": trailing_stop,
        }
        if stop_level is not None:
            payload.update({"stopLevel": stop_level})
        if stop_distance is not None:
            payload.update({"stopDistance": stop_distance})
        if stop_amount is not None:
            payload.update({"stopAmount": stop_amount})
        if profit_level is not None:
            payload.update({"profitLevel": profit_level})
        if profit_distance is not None:
            payload.update({"profitDistance": profit_distance})
        if profit_amount is not None:
            payload.update({"profitAmount": profit_amount})

        response = await self.__make_request__("post", url, payload=payload)
        final_data = await self.__confirmation__(response.json()["dealReference"])
        await self.__log_out__()
        return final_data

    # Closes a specific position with the deal_id
    async def close_position(self, deal_id):
        await self.__create_session__()
        url = f"{self.server}/api/v1/positions/{deal_id}"
        response = await self.__make_request__("delete", url, payload="")
        final_data = await self.__confirmation__(response.json()["dealReference"])
        await self.__log_out__()
        return final_data

    # Update the position
    async def update_position(
        self,
        deal_id,
        guaranteed_stop=False,
        trailing_stop=False,
        stop_level=None,
        stop_distance=None,
        stop_amount=None,
        profit_level=None,
        profit_distance=None,
        profit_amount=None,
    ):
        payload = {"guaranteedStop": guaranteed_stop, "trailingStop": trailing_stop}
        if stop_level is not None:
            payload.update({"stopLevel": stop_level})
        if stop_distance is not None:
            payload.update({"stopDistance": stop_distance})
        if stop_amount is not None:
            payload.update({"stopAmount": stop_amount})
        if profit_level is not None:
            payload.update({"profitLevel": profit_level})
        if profit_distance is not None:
            payload.update({"profitDistance": profit_distance})
        if profit_amount is not None:
            payload.update({"profitAmount": profit_amount})

        await self.__create_session__()
        url = f"{self.server}/api/v1/positions/{deal_id}"
        response = await self.__make_request__("put", url, payload=payload)
        final_data = await self.__confirmation__(response.json()["dealReference"])
        await self.__log_out__()
        return final_data

    # Returns all open working orders for the active account
    async def all_working_orders(self):
        await self.__create_session__()
        url = f"{self.server}/api/v1/workingorders"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

    # Create a limit or stop order
    async def create_working_order(
        self,
        epic,
        direction,
        size,
        level,
        type,
        guaranteed_stop=False,
        trailing_stop=False,
        stop_level=None,
        stop_distance=None,
        stop_amount=None,
        profit_level=None,
        profit_distance=None,
        profit_amount=None,
    ):
        await self.__create_session__()
        url = f"{self.server}/api/v1/workingorders"
        payload = {
            "epic": epic,
            "direction": direction.upper(),
            "size": str(size),
            "level": level,
            "type": type,
            "guaranteedStop": guaranteed_stop,
            "trailingStop": trailing_stop,
        }
        if stop_level is not None:
            payload.update({"stopLevel": stop_level})
        if stop_distance is not None:
            payload.update({"stopDistance": stop_distance})
        if stop_amount is not None:
            payload.update({"stopAmount": stop_amount})
        if profit_level is not None:
            payload.update({"profitLevel": profit_level})
        if profit_distance is not None:
            payload.update({"profitDistance": profit_distance})
        if profit_amount is not None:
            payload.update({"profitAmount": profit_amount})

        response = await self.__make_request__("post", url, payload=payload)
        final_data = await self.__confirmation__(response.json()["dealReference"])
        await self.__log_out__()
        return final_data

    # Update a limit or stop order
    async def update_working_order(
        self,
        deal_id,
        level,
        guaranteed_stop=False,
        trailing_stop=False,
        stop_level=None,
        stop_distance=None,
        stop_amount=None,
        profit_level=None,
        profit_distance=None,
        profit_amount=None,
    ):
        payload = {
            "guaranteedStop": guaranteed_stop,
            "trailingStop": trailing_stop,
            "level": level,
        }
        if stop_level is not None:
            payload.update({"stopLevel": stop_level})
        if stop_distance is not None:
            payload.update({"stopDistance": stop_distance})
        if stop_amount is not None:
            payload.update({"stopAmount": stop_amount})
        if profit_level is not None:
            payload.update({"profitLevel": profit_level})
        if profit_distance is not None:
            payload.update({"profitDistance": profit_distance})
        if profit_amount is not None:
            payload.update({"profitAmount": profit_amount})

        await self.__create_session__()
        url = f"{self.server}/api/v1/workingorders/{deal_id}"
        response = await self.__make_request__("put", url, payload=payload)
        final_data = await self.__confirmation__(response.json()["dealReference"])
        await self.__log_out__()
        return final_data

    # Delete a limit or stop order
    async def delete_working_order(self, deal_id):
        await self.__create_session__()
        url = f"{self.server}/api/v1/workingorders/{deal_id}"
        response = await self.__make_request__("delete", url, payload="")
        final_data = await self.__confirmation__(response.json()["dealReference"])
        await self.__log_out__()
        return final_data

    # Returns all top-level nodes (market categories) in the market navigation hierarchy
    async def all_top(self):
        await self.__create_session__()
        url = f"{self.server}/api/v1/marketnavigation"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

    # Returns all sub-nodes (markets) of the given node (market category) in the market navigation hierarchy
    async def all_top_sub(self, node_id):
        await self.__create_session__()
        url = f"{self.server}/api/v1/marketnavigation/{node_id}?limit=500"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

    # Returns the details of the given markets
    async def market_details(self, market):
        await self.__create_session__()
        url = f"{self.server}/api/v1/markets?searchTerm={market}"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

    # Returns the details of the given market
    async def single_market_details(self, epic):
        await self.__create_session__()
        url = f"{self.server}/api/v1/markets/{epic}"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

    # Returns historical prices for a particular instrument
    async def prices(self, epic, resolution="MINUTE", max=10):
        await self.__create_session__()
        url = f"{self.server}/api/v1/prices/{epic}?resolution={resolution}&max={max}"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

    # Client sentiment for market
    async def client_sentiment(self, market_id):
        await self.__create_session__()
        url = f"{self.server}/api/v1/clientsentiment/{market_id}"
        response = await self.__make_request__("get", url, payload="")
        await self.__log_out__()
        return response.json()

    async def __log_out__(self):
        await self.__make_request__("delete", f"{self.server}/api/v1/session")
        self.headers = {
            "X-CAP-API-KEY": self.api_key,
            "content-type": "application/json",
        }
