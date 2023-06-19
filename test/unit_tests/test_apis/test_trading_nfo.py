from unittest.mock import AsyncMock

import pytest
from asynctest import MagicMock
from sqlalchemy import select

from app.database.models import StrategyModel
from test.unit_tests.test_data import get_test_post_trade_payload
from test.utils import create_closed_trades


@pytest.mark.asyncio
async def test_trading_nfo_options_with_invalid_strategy_id(test_async_client):
    payload = get_test_post_trade_payload()
    mock_celery_buy_task = MagicMock()
    mock_celery_buy_task.return_value = AsyncMock()

    response = await test_async_client.post("/api/trading/nfo/options", json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid strategy_id"}
    assert not mock_celery_buy_task.called


@pytest.mark.asyncio
async def test_trading_nfo_options_with_valid_strategy_id(
    test_async_client, monkeypatch, test_async_session
):
    await create_closed_trades(users=1, strategies=1)
    strategy_model = await test_async_session.scalar(select(StrategyModel))

    payload = get_test_post_trade_payload()
    payload["strategy_id"] = str(strategy_model.id)

    mock_celery_buy_task = MagicMock()
    mock_celery_buy_task.delay = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.endpoints.trading.task_buying_trade", mock_celery_buy_task)

    response = await test_async_client.post("/api/trading/nfo/options", json=payload)

    assert response.status_code == 200
    assert response.json() == {"message": "Trade initiated successfully"}
    assert not mock_celery_buy_task.called
