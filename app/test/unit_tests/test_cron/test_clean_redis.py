from datetime import datetime
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from aioredis import Redis
from cron.clean_redis import clean_redis
from cron.clean_redis import contains_date
from cron.clean_redis import delete_keys
from cron.clean_redis import get_key_value_mappings
from cron.clean_redis import get_keys_with_date
from cron.clean_redis import get_stale_keys
from cron.clean_redis import is_stale_expiry

from app.utils.constants import ALICE_BLUE_EXPIRY_DATE_FORMAT
from app.utils.constants import ANGELONE_EXPIRY_DATE_FORMAT


@pytest.mark.asyncio
async def test_contains_date():
    assert contains_date("key_01Jan21") is True
    assert contains_date("key_without_date") is False


@pytest.mark.asyncio
async def test_get_keys_with_date():
    keys = ["key_01Jan21", "key_without_date", "another_key_02Feb22"]
    result = get_keys_with_date(keys)
    assert result == ["key_01Jan21", "another_key_02Feb22"]


@pytest.mark.asyncio
async def test_get_values_of_keys():
    redis_client = AsyncMock(Redis)
    # Mock the pipeline context manager
    pipeline_mock = redis_client.pipeline.return_value.__aenter__.return_value
    pipeline_mock.type.side_effect = ["string", "hash"]
    pipeline_mock.execute.side_effect = [
        ["string", "hash"],  # First call to execute() for key_types
        [
            "value1",
        ],  # Second call to execute() for values
    ]

    keys_with_date = ["key1", "key2"]
    result = await get_key_value_mappings(redis_client, keys_with_date)
    assert result == {"key1": "value1"}


@pytest.mark.asyncio
async def test_is_stale_expiry():
    current_date = datetime(2023, 1, 1).date()
    assert is_stale_expiry("2022-12-31", current_date) is True
    assert is_stale_expiry("2023-01-02", current_date) is False
    assert is_stale_expiry("", current_date) is False


@pytest.mark.asyncio
async def test_get_stale_keys():
    yesterdays_date = datetime.today().date() - timedelta(days=1)
    tomorrows_date = datetime.today().date() + timedelta(days=1)
    key_value_mappings = {
        "key1": f'{{"expiry": "{yesterdays_date}"}}',
        "key2": f'{{"expiry": "{tomorrows_date}"}}',
    }
    result = get_stale_keys(key_value_mappings)
    assert result == ["key1"]


@pytest.mark.asyncio
async def test_delete_keys():
    redis_client = AsyncMock(Redis)
    keys_to_delete = ["key1", "key2"]
    # mock delete
    redis_client.delete = AsyncMock(return_value=None)

    await delete_keys(redis_client, keys_to_delete)
    redis_client.delete.assert_called_with("key1", "key2")


@pytest.mark.asyncio
async def test_clean_redis():
    yesterdays_date = (datetime.today().date() - timedelta(days=1)).strftime(
        ANGELONE_EXPIRY_DATE_FORMAT
    )
    tomorrows_date = (datetime.today().date() + timedelta(days=1)).strftime(
        ALICE_BLUE_EXPIRY_DATE_FORMAT
    )

    redis_client = AsyncMock(Redis)

    # mock keys
    redis_client.keys = AsyncMock(
        return_value=[
            f"key_{yesterdays_date}",
            "key_without_date",
            f"another_key_{tomorrows_date}",
        ]
    )

    # mock types and values
    pipeline_mock = redis_client.pipeline.return_value.__aenter__.return_value
    pipeline_mock.type.side_effect = ["string", "hash"]
    pipeline_mock.execute.side_effect = [
        ["string", "string"],  # First call to execute() for key_types
        [
            f'{{"expiry": "{yesterdays_date}"}}',
            f'{{"expiry": "{tomorrows_date}"}}',
        ],  # Second call to execute() for values
    ]

    # mock delete
    redis_client.delete = AsyncMock(return_value=None)

    await clean_redis(redis_client)
    redis_client.keys.assert_called_once()
    redis_client.delete.assert_called_once_with(f"key_{yesterdays_date}")
