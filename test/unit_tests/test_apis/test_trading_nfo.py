from unittest.mock import AsyncMock

import pytest
from asynctest import MagicMock
from sqlalchemy import Select

from app.database.models import StrategyModel
from test.conftest import create_ecosystem
from test.unit_tests.test_data import get_test_post_trade_payload


@pytest.mark.asyncio
async def test_trading_nfo_options_with_invalid_strategy_id(async_client):
    payload = get_test_post_trade_payload()
    mock_celery_buy_task = MagicMock()
    mock_celery_buy_task.return_value = AsyncMock()

    response = await async_client.post("/api/trading/nfo/options", json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid strategy_id"}
    assert not mock_celery_buy_task.called


@pytest.mark.asyncio
async def test_trading_nfo_options_with_valid_strategy_id(
    async_session, async_client, monkeypatch
):
    await create_ecosystem(async_session, users=1, strategies=1)
    fetch_strategy_query_ = await async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()

    payload = get_test_post_trade_payload()
    payload["strategy_id"] = str(strategy_model.id)

    mock_celery_buy_task = MagicMock()
    mock_celery_buy_task.delay.return_value = AsyncMock()
    monkeypatch.setattr("app.api.endpoints.trading.task_buying_trade", mock_celery_buy_task)

    response = await async_client.post("/api/trading/nfo/options", json=payload)

    assert response.status_code == 200
    assert response.json() == {"message": "Trade initiated successfully"}
    assert not mock_celery_buy_task.called
