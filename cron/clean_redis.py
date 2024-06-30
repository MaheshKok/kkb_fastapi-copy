import asyncio
import datetime
import logging
import re

from dateutil import parser

from app.core.config import get_config
from app.database.base import get_redis_client


logging.basicConfig(level=logging.INFO)


async def clean_redis():
    logging.info("Starting clean_redis...")
    config = get_config()
    redis_client = get_redis_client(config)
    keys = await redis_client.keys()

    keys_with_date = []
    for key in keys:
        match = re.search("\d{2}[a-zA-Z]{3}\d{2}", key)  # noqa
        if match:
            keys_with_date.append(key)
    logging.info(f"Found {len(keys_with_date)} keys with a date.")

    batch_size = 30000
    values = []
    keys_to_process = []
    for i in range(0, len(keys_with_date), batch_size):
        batch_keys = keys_with_date[i : i + batch_size]
        pipe = redis_client.pipeline()
        for key in batch_keys:
            pipe.type(key)
        types = await pipe.execute()

        string_keys = [k for k, t in zip(batch_keys, types) if t == "string"]
        logging.info(f"Found {len(string_keys)} string keys.")

        if string_keys:
            pipe = redis_client.pipeline()
            for key in string_keys:
                pipe.get(key)
            batch_values = await pipe.execute()

            keys_to_process.extend(string_keys)
            values.extend(batch_values)

    logging.info(f"Fetched {len(values)} values for string keys")

    keys_to_delete = []
    current_date = datetime.date.today()

    for key, value in zip(keys_with_date, values):
        value_dict = eval(value)
        if "expiry" in value_dict or "Expiry Date" in value_dict:
            date_to_compare_with = value_dict.get("expiry", value_dict.get("Expiry Date"))
            if not date_to_compare_with:
                continue
            try:
                expiry_date = parser.parse(date_to_compare_with).date()
                if expiry_date < current_date:
                    keys_to_delete.append(key)
            except Exception:
                logging.warning(f"invalid date: {date_to_compare_with}")

    logging.info(f"Found {len(keys_to_delete)} keys to delete.")

    # delete keys in batch
    for i in range(0, len(keys_to_delete), 10000):  # Delete keys in chunks of 1000
        chunk = keys_to_delete[i : i + 10000]
        await redis_client.delete(*chunk)
    logging.info(f"Deleted {len(keys_to_delete)} keys.")
    return len(keys_to_delete)


if __name__ == "__main__":
    asyncio.run(clean_redis())
