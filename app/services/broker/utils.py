import asyncio
import base64
import bisect
import datetime
import hashlib
import os
from collections import defaultdict

from aioredis import Redis
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import modes
from dateutil import parser
from fastapi import HTTPException
from httpx import AsyncClient
from pya3 import OrderType
from pya3 import ProductType
from pya3 import TransactionType
from sqlalchemy import select

from app.api.utils import update_session_token
from app.database.models import BrokerModel
from app.database.session_manager.db_session import Database
from app.schemas.broker import BrokerSchema
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.services.broker.alice_blue import Pya3Aliceblue
from app.services.broker.alice_blue import logging
from app.utils.constants import OptionType
from app.utils.constants import Status


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


async def get_pya3_obj(async_redis_client, broker_id, async_httpx_client) -> Pya3Aliceblue:
    broker_json = await async_redis_client.get(broker_id)

    if broker_json:
        broker_schema = BrokerSchema.parse_raw(broker_json)
    else:
        async with Database() as async_session:
            # We have a cron that update session token every 1 hour,
            # but frequency can be brought down to 1 day, but we dont know when it expires
            # but due to some reason it doesnt work then get session token updated using get_alice_blue_obj
            # and then create pya3_obj again and we would need to do it in place_order

            # TODO: fetch it from redis
            fetch_broker_query = await async_session.execute(
                select(BrokerModel).filter_by(id=str(broker_id))
            )
            broker_model = fetch_broker_query.scalars().one_or_none()

            if not broker_model:
                raise HTTPException(status_code=404, detail=f"Broker: {broker_id} not found")
            broker_schema = BrokerSchema.model_validate(broker_model)
            await async_redis_client.set(broker_id, broker_schema.json())

    # TODO: update cron updating alice blue access token to update redis as well with the latest access token
    pya3_obj = Pya3Aliceblue(
        user_id=broker_schema.username,
        password=broker_schema.password,
        api_key=broker_schema.api_key,
        totp=broker_schema.totp,
        twoFA=broker_schema.twoFA,
        app_id=broker_schema.app_id,
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

    order_status = "default order status"
    for _ in range(20):
        try:
            order_status = await pya3_obj.get_order_history(order_id)
            if order_status["Status"] == Status.COMPLETE:
                return order_status["Avgprc"]
            elif order_status["Status"] == Status.REJECTED:
                # TODO: send whatsapp message using Twilio API instead of Telegram
                # Rejection Reason: order_status["RejReason"]
                logging.error(
                    f"buy order rejected for order_id: {order_id} , order_status: {order_status}"
                )
                # capture_exception(
                #     Exception(
                #         f"buy order not placed for: {instrument.name} , place_order_response: {place_order_response}"
                #     )
                # )
                raise HTTPException(status_code=403, detail=order_status["RejReason"])
            else:
                logging.warning(
                    f"buy order not placed for order_id: {order_id} , order_status: {order_status['Status']}, order_status_reason: {order_status['RejReason']}"
                )
                await asyncio.sleep(0.5)
        except Exception as e:
            # capture_exception(
            #     Exception(
            #         f"buy order not placed for: {instrument.name} , place_order_response: {place_order_response}"
            #     )
            # )
            logging.error(
                f"buy order not placed for order_id: {order_id} , order_status: {order_status}, error:{e}"
            )

            await asyncio.sleep(0.5)
    else:
        # capture_exception(
        #     Exception(
        #         f"order_id: {order_id} did not complete in 10 seconds, strike_exitprice_dict: {strike_exitprice_dict}"
        #     )
        # )
        logging.error(
            f"order_id: {order_id} did not complete in 10 seconds, last fetched status: {order_status}"
        )

        return None


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
    # get execution time as per IST
    execution_time = (
        datetime.datetime.now().utcnow() + datetime.timedelta(hours=5, minutes=30)
    ).replace(microsecond=0)
    instr_token = instrument.token

    place_order_response = await pya3_obj.place_order(
        transaction_type=TransactionType.Buy if is_buy else TransactionType.Sell,
        instrument=instrument,
        quantity=quantity,
        order_type=OrderType.Market,
        product_type=ProductType.Delivery,
    )

    if "NOrdNo" in place_order_response:
        return strike, place_order_response["NOrdNo"]

    if (
        place_order_response["stat"] == "Not_ok"
        and "401 - Unauthorized" == place_order_response["emsg"]
    ):
        # update the session token and try again
        session_id = await update_session_token(
            pya3_obj=pya3_obj, async_redis_client=async_redis_client
        )
        pya3_obj.session_id = session_id

        place_order_response = await pya3_obj.place_order(
            transaction_type=TransactionType.Buy if is_buy else TransactionType.Sell,
            instrument=instrument,
            quantity=quantity,
            order_type=OrderType.Market,
            product_type=ProductType.Delivery,
        )

        if "NOrdNo" in place_order_response:
            return strike, place_order_response["NOrdNo"]

    # TODO: i think below code is stale as i dont know which scenario below code handles,
    # below code was developed when i assumed some scenario might occur which i dont remember now
    # now i dont think below code is required, but still keeping it for now
    logging.error(f"place_order_response: {place_order_response}")

    # get order book and check if order is placed
    orders = await pya3_obj.order_data()
    # filter orders by instrument token
    token_orders = [order for order in orders if order["token"] == str(instr_token)]
    if not token_orders:
        # install sentry and uncomment below line
        # capture_exception(
        #     Exception(
        #         f"buy order not placed for: {instrument.name} , place_order_response: {place_order_response}"
        #     )
        # )
        if is_buy:
            raise Exception(f"order not placed, place_order_response: {place_order_response}")
        else:
            # if sell order_id is not fetched, then assume it has been executed and
            # try to fetch avg price from option chain which is done later in code
            return strike, None

    # sort orders by orderentrytime, but first convert orderentrytime to datetime using parser
    sorted_token_orders = sorted(
        token_orders, key=lambda order: parser.parse(order["orderentrytime"])
    )

    execution_time_orders_lst = [
        (parser.parse(order["orderentrytime"]), order) for order in sorted_token_orders
    ]
    execution_time_lst = [ele[0] for ele in execution_time_orders_lst]
    # get order which was placed just after execution_time
    execution_time_index = bisect.bisect_left(execution_time_lst, execution_time)
    # if order is not placed, then raise exception
    if (
        execution_time_index == len(execution_time_lst)
        and execution_time_lst[-1] != execution_time
    ):
        # capture_exception(
        #     Exception(
        #         f"buy order not placed for: {instrument.name} , place_order_response: {place_order_response}"
        #     )
        # )
        if is_buy:
            raise Exception(f"order not placed, place_order_response: {place_order_response}")
        else:
            # if sell order_id is not fetched, then assume it has been executed and
            # try to fetch avg price from option chain which is done later in code
            return strike, None

    placed_order = execution_time_orders_lst[execution_time_index][1]
    # Nstordno is the order id
    return strike, placed_order["Nstordno"]


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
            order_status = None
            if order_id:
                for _ in range(20):
                    try:
                        order_status = await pya3_obj.get_order_history(order_id)
                        if order_status["Status"] == Status.COMPLETE:
                            strike_exitprice_dict[strike] = float(order_status["Avgprc"])
                            break
                    except Exception as e:
                        # capture_exception(
                        #     Exception(
                        #         f"sell order for order_id: [ {order_id} ] has order_status: [ {order_status} ]"
                        #     )
                        # )
                        logging.error(
                            f"sell order for order_id: [ {order_id} ] has order_status: [ {order_status} ], error: {e}"
                        )
                    await asyncio.sleep(0.5)
                else:
                    logging.error(
                        f"sell order for order_id: [ {order_id} ], could not be closed in 10 seconds and its last order_status: {order_status}"
                    )
                    # capture_exception(
                    #     Exception(
                    #         f"sell order for order_id: [ {order_id} ], could not be closed in 10 seconds and its last order_status: {order_status}"
                    #     )
                    # )
                    strike_exitprice_dict[strike] = None
            else:
                # assing None to strike which is being closed and later its avg price will be fetched from option chain
                logging.error(f"sell order_id not found for strike: {strike}")
                # capture_exception(
                #     Exception(
                #          f"sell order_id not found for strike: {strike}"
                #     )
                # )
                strike_exitprice_dict[strike] = None

        return strike_exitprice_dict


# TODO: improve logging and delegate exception handling
