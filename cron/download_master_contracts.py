import asyncio
import io
import json
from datetime import datetime

import httpx
import pandas as pd

from app.core.config import get_config
from app.database.base import get_redis_client
from app.utils.constants import AB_NFO_CONTRACTS_URL
from app.utils.constants import INSTRUMENT_COLUMN


async def download_master_contract():
    config = get_config()
    redis_client = get_redis_client(config)

    response = await httpx.AsyncClient().get(AB_NFO_CONTRACTS_URL)
    # Read the CSV file
    data_stream = io.StringIO(response.text)
    df = pd.read_csv(data_stream)

    # Construct the dictionary
    # Note: there are many duplicate keys in the CSV file and they are exact duplicates so dont worry about it
    full_name_row_dict = {}
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        key = row_dict[INSTRUMENT_COLUMN]
        value = json.dumps(row_dict)
        full_name_row_dict[key] = value

    print("Setting keys in Redis")
    start_time = datetime.now()

    # Split the dictionary into smaller chunks
    chunk_size = 10000
    dict_chunks = [
        dict(list(full_name_row_dict.items())[i : i + chunk_size])
        for i in range(0, len(full_name_row_dict), chunk_size)
    ]

    # Use a pipeline to set each chunk of key-value pairs in Redis
    for chunk in dict_chunks:
        with redis_client.pipeline() as pipe:
            for key, value in chunk.items():
                pipe.set(key, value)
            pipe.execute()

    print(f"Time taken to set {len(full_name_row_dict)} keys: {datetime.now() - start_time}")


if __name__ == "__main__":
    asyncio.run(download_master_contract())
