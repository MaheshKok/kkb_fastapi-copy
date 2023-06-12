from unittest.mock import AsyncMock

import pytest
from asynctest import MagicMock

from app.utils.option_chain import get_option_chain
from test.unit_tests.test_data import get_ce_option_chain
from test.unit_tests.test_data import get_pe_option_chain


@pytest.mark.asyncio
async def test_get_option_chain_ce(monkeypatch):
    ce_option_chain = get_ce_option_chain()
    mock_redis = MagicMock()
    mock_redis.hgetall = AsyncMock(return_value=ce_option_chain)

    monkeypatch.setattr("app.utils.option_chain.redis", mock_redis)

    # Call the function that uses redis.hgetall
    option_chain = await get_option_chain("symbol", "expiry", option_type="CE", is_future=False)

    # Assertions or further tests based on the returned option_chain
    assert option_chain == dict(
        sorted([(float(key), float(value)) for key, value in ce_option_chain.items()])
    )


@pytest.mark.asyncio
async def test_get_option_chain_pe(monkeypatch):
    pe_option_chain = get_pe_option_chain()
    mock_redis = MagicMock()
    mock_redis.hgetall = AsyncMock(return_value=pe_option_chain)

    monkeypatch.setattr("app.utils.option_chain.redis", mock_redis)

    # Call the function that uses redis.hgetall
    option_chain = await get_option_chain("symbol", "expiry", option_type="PE", is_future=False)

    # Assertions or further tests based on the returned option_chain
    assert option_chain == dict(
        sorted([(float(key), float(value)) for key, value in pe_option_chain.items()])
    )
