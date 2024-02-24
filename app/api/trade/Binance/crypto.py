import asyncio
import logging

from binance import AsyncClient as BinanceAsyncClient
from fastapi import APIRouter

from app.api.trade import trading_router
from app.schemas.enums import SignalTypeEnum
from app.schemas.trade import BinanceFuturesPayloadSchema


binance_router = APIRouter(
    prefix=f"{trading_router.prefix}/binance",
    tags=["binance"],
)


@binance_router.post("/futures", status_code=200)
async def post_binance_futures(futures_payload_schema: BinanceFuturesPayloadSchema):
    if futures_payload_schema.is_live:
        api_key = "8eV439YeuT1JM5mYF0mX34jKSOakRukolfGayaF9Sj6FMBC4FV1qTHKUqycrpQ4T"
        api_secret = "gFdKzcNXMvDoNfy1YbLNuS0hifnpE5gphs9iTkkyECv6TuYz5pRM4U4vwoNPQy6Q"
        bnc_async_client = BinanceAsyncClient(
            api_key=api_key, api_secret=api_secret, testnet=False
        )
    else:
        api_key = "75d5c54b190c224d6527440534ffe2bfa2afb34c0ccae79beadf560b9d2c5c56"
        api_secret = "db135fa6b2de30c06046891cc1eecfb50fddff0a560043dcd515fd9a57807a37"
        bnc_async_client = BinanceAsyncClient(
            api_key=api_key, api_secret=api_secret, testnet=True
        )

    ltp = round(float(futures_payload_schema.ltp), 2)
    if futures_payload_schema.symbol == "BTCUSDT":
        offset = 5
        ltp = int(ltp)
    elif futures_payload_schema.symbol == "ETHUSDT":
        offset = 0.5
    elif futures_payload_schema.symbol == "LTCUSDT":
        offset = 0.05
    elif futures_payload_schema.symbol == "ETCUSDT":
        offset = 0.03
    else:
        return f"Invalid Symbol: {futures_payload_schema.symbol}"

    if futures_payload_schema.side == SignalTypeEnum.BUY.value.upper():
        price = round(ltp + offset, 2)
    else:
        price = round(ltp - offset, 2)

    attempt = 1
    while attempt <= 10:
        try:
            existing_position = await bnc_async_client.futures_position_information(
                symbol=futures_payload_schema.symbol
            )

            existing_quantity = 0
            if existing_position:
                existing_quantity = abs(float(existing_position[0]["positionAmt"]))

            quantity_to_place = round(futures_payload_schema.quantity + existing_quantity, 2)
            result = await bnc_async_client.futures_create_order(
                symbol=futures_payload_schema.symbol,
                side=futures_payload_schema.side,
                type=futures_payload_schema.type,
                quantity=quantity_to_place,
                timeinforce="GTC",
                price=price,
            )
            return result
        except Exception as e:
            msg = f"Error occured while placing binance order, Error: {e}"
            logging.error(msg)
            attempt += 1
            await asyncio.sleep(1)
