import asyncio
import io
import json
import logging

import httpx
import pandas as pd

from app.core.config import get_config
from app.database.base import get_redis_client


async def get_expiry_list_from_alice_blue():
    api = "https://v2api.aliceblueonline.com/restpy/static/contract_master/NFO.csv"

    response = await httpx.AsyncClient().get(api)
    data_stream = io.StringIO(response.text)
    df = pd.read_csv(data_stream)
    result = {}
    for (instrument_type, symbol), group in df.groupby(["Instrument Type", "Symbol"]):
        if instrument_type not in result:
            result[instrument_type] = {}
        expiry_dates = sorted(set(group["Expiry Date"].tolist()))
        result[instrument_type][symbol] = expiry_dates

    config = get_config()
    async_redis_client = get_redis_client(config)
    for instrument_type, expiry in result.items():
        await async_redis_client.set(instrument_type, json.dumps(expiry))

    logging.info("expiry set from alice blue to redis")


if __name__ == "__main__":
    asyncio.run(get_expiry_list_from_alice_blue())
