import asyncio
import datetime
import logging
import re
from typing import List

from aioredis import Redis
from dateutil import parser

from app.core.config import get_config
from app.database.base import get_redis_client


logging.basicConfig(level=logging.INFO)

DATE_PATTERN = re.compile(r"\d{2}[a-zA-Z]{3}\d{2}")


def contains_date(key: str) -> bool:
    """Check if the key contains a date pattern."""
    return bool(DATE_PATTERN.search(key))


def get_keys_with_date(keys: List[str]) -> List[str]:
    """Filter keys that contain a date pattern."""
    keys_with_date = [key for key in keys if contains_date(key)]
    logging.info(f"Found {len(keys_with_date)} keys with a date.")
    return keys_with_date


async def get_key_value_mappings(
    redis_client: Redis, keys_with_date: List[str]
) -> dict[str, str]:
    """Fetch values of keys that are of type 'string'."""
    batch_size = 30000
    key_value_mappings = {}
    for i in range(0, len(keys_with_date), batch_size):
        batch_keys = keys_with_date[i : i + batch_size]
        async with redis_client.pipeline() as pipe:
            for key in batch_keys:
                pipe.type(key)
            key_types = await pipe.execute()

        string_keys = [
            key for key, key_type in zip(batch_keys, key_types) if key_type == "string"
        ]
        logging.info(f"Found {len(string_keys)} string keys.")

        if string_keys:
            async with redis_client.pipeline() as pipe:
                for key in string_keys:
                    pipe.get(key)
                batch_values = await pipe.execute()

            key_value_mappings = {**key_value_mappings, **dict(zip(string_keys, batch_values))}
    logging.info(f"Fetched {len(key_value_mappings)} values for string keys")
    return key_value_mappings


def is_stale_expiry(value: str, current_date: datetime.date) -> bool:
    """Check if the expiry date is stale."""
    if not value:
        return False

    expiry_date = parser.parse(value).date()
    return expiry_date < current_date


def get_stale_keys(key_value_mappings: dict[str, str]) -> List[str]:
    """Identify keys with stale expiry dates."""
    keys_to_delete = []
    current_date = datetime.date.today()

    for key, value in key_value_mappings.items():
        value_dict = eval(value)
        expiry_date_str = value_dict.get("expiry") or value_dict.get("Expiry Date")
        if expiry_date_str and is_stale_expiry(expiry_date_str, current_date):
            keys_to_delete.append(key)

    logging.info(f"Found {len(keys_to_delete)} keys to delete.")
    return keys_to_delete


async def delete_keys(redis_client: Redis, keys_to_delete: List[str]) -> None:
    """Delete keys in batches."""
    batch_size = 10000
    for i in range(0, len(keys_to_delete), batch_size):
        chunk = keys_to_delete[i : i + batch_size]
        await redis_client.delete(*chunk)
    logging.info(f"Deleted {len(keys_to_delete)} keys.")


async def clean_redis(redis_client: Redis) -> None:
    """Main function to clean Redis."""
    logging.info("Starting clean_redis...")
    keys = await redis_client.keys()

    keys_with_date = get_keys_with_date(keys)
    key_value_mappings = await get_key_value_mappings(redis_client, keys_with_date)
    stale_keys = get_stale_keys(key_value_mappings)
    await delete_keys(redis_client, stale_keys)


if __name__ == "__main__":
    config = get_config()
    redis_client = get_redis_client(config)
    asyncio.run(clean_redis(redis_client))
