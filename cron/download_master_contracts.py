import asyncio
import datetime
import io
import json
from itertools import islice

import httpx
import pandas as pd
from cron.clean_redis import date_in_key
from cron.clean_redis import is_stale_expiry

from app.core.config import get_config
from app.database.base import get_redis_client
from app.utils.constants import AB_NFO_CONTRACTS_URL
from app.utils.constants import ANGELONE_ONE_CONTRACTS_URL
from app.utils.constants import INSTRUMENT_COLUMN
from app.utils.constants import NAME_STR
from app.utils.constants import SYMBOL_STR


async def push_alice_blue_instruments(redis_client):
    response = await httpx.AsyncClient().get(AB_NFO_CONTRACTS_URL)
    # Read the CSV file
    data_stream = io.StringIO(response.text)
    df = pd.read_csv(data_stream)
    current_date = datetime.date.today()

    # Construct the dictionary
    # Note: there are many duplicate keys in the CSV file and they are exact duplicates so don't worry about it
    full_name_row_dict = {}
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        key = row_dict[INSTRUMENT_COLUMN]
        value = json.dumps(row_dict)
        if date_in_key(key):
            expiry_date_str = row_dict.get("expiry", row_dict.get("Expiry Date"))
            if not is_stale_expiry(expiry_date_str, current_date):
                full_name_row_dict[key] = value
        else:
            full_name_row_dict[key] = value

    print(f"Setting alice blue [ {len(full_name_row_dict)} ] keys in Redis")
    start_time = datetime.datetime.now()

    # Split the dictionary into smaller chunks
    chunk_size = 10000
    dict_chunks = [
        dict(list(full_name_row_dict.items())[i : i + chunk_size])
        for i in range(0, len(full_name_row_dict), chunk_size)
    ]

    # Use a pipeline to set each chunk of key-value pairs in Redis
    async with redis_client.pipeline() as pipe:
        for chunk in dict_chunks:
            pipe.mset(chunk)
            await pipe.execute()

    print(
        f"Time taken to set Alice Blue {len(full_name_row_dict)} keys: {datetime.datetime.now() - start_time}"
    )


async def push_angel_one_instruments(redis_client, symbols=None):
    response = await httpx.AsyncClient().get(ANGELONE_ONE_CONTRACTS_URL)
    data_stream = json.loads(response.text)
    df = pd.DataFrame(data_stream)

    current_date = datetime.date.today()
    # Construct the dictionary
    full_symbol_to_row_mapping = {}
    if not symbols:
        for _, row in df.iterrows():
            row_dict = row.to_dict()
            trading_symbol = row_dict[SYMBOL_STR]
            value = json.dumps(row_dict)
            if date_in_key(trading_symbol):
                expiry_date_str = row_dict.get("expiry", row_dict.get("Expiry Date"))
                if not is_stale_expiry(expiry_date_str, current_date):
                    full_symbol_to_row_mapping[trading_symbol] = value
            else:
                full_symbol_to_row_mapping[trading_symbol] = value
    else:
        for _, row in df.iterrows():
            row_dict = row.to_dict()
            symbol = row_dict[NAME_STR]
            trading_symbol = row_dict[SYMBOL_STR]
            if symbol in symbols:
                value = json.dumps(row_dict)
                if date_in_key(trading_symbol):
                    expiry_date_str = row_dict.get("expiry", row_dict.get("Expiry Date"))
                    if not is_stale_expiry(expiry_date_str, current_date):
                        full_symbol_to_row_mapping[trading_symbol] = value
                else:
                    full_symbol_to_row_mapping[trading_symbol] = value

    print(f"Setting angel one  [ {len(full_symbol_to_row_mapping)} ]  keys in redis")
    start_time = datetime.datetime.now()

    # # Split the dictionary into smaller chunks
    def chunked_dict(d, chunk_size):
        it = iter(d)
        for _ in range(0, len(d), chunk_size):
            yield {k: d[k] for k in islice(it, chunk_size)}

    # # Use a pipeline to set each chunk of key-value pairs in Redis
    async with redis_client.pipeline() as pipe:
        for chunk in chunked_dict(full_symbol_to_row_mapping, chunk_size=1000):
            pipe.mset(chunk)
            # execute the pipeline after each chunk, otherwise it will throw broken pipe error due to large data
            await pipe.execute()

    print(
        f"Time taken to set Angel One {len(full_symbol_to_row_mapping)} keys: {datetime.datetime.now() - start_time}"
    )


async def download_master_contract():
    config = get_config()
    redis_client = get_redis_client(config)
    await asyncio.gather(
        push_angel_one_instruments(redis_client), push_alice_blue_instruments(redis_client)
    )


if __name__ == "__main__":
    asyncio.run(download_master_contract())
