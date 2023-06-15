from unittest.mock import AsyncMock

import pytest
from asynctest import MagicMock
from sqlalchemy import Select

from app.database.models import StrategyModel
from test.conftest import create_closed_trades
from test.unit_tests.test_data import get_test_post_trade_payload


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
    test_async_session, test_async_client, monkeypatch
):
    await create_closed_trades(test_async_session, users=1, strategies=1)
    fetch_strategy_query_ = await test_async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()

    payload = get_test_post_trade_payload()
    payload["strategy_id"] = str(strategy_model.id)

    mock_celery_buy_task = MagicMock()
    mock_celery_buy_task.delay = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.endpoints.trading.task_buying_trade", mock_celery_buy_task)

    response = await test_async_client.post("/api/trading/nfo/options", json=payload)

    assert response.status_code == 200
    assert response.json() == {"message": "Trade initiated successfully"}
    assert not mock_celery_buy_task.called
