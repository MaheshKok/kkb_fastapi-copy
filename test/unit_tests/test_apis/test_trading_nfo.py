from unittest.mock import AsyncMock

import pytest
from fastapi_sa.database import db
from sqlalchemy import select

from app.database.models import StrategyModel
from test.unit_tests.test_data import get_test_post_trade_payload
from test.utils import create_closed_trades


@pytest.mark.asyncio
async def test_trading_nfo_options_with_valid_strategy_id(test_async_client, monkeypatch):
    await create_closed_trades(users=1, strategies=1)

    async with db():
        strategy_model = await db.session.scalar(select(StrategyModel))
        payload = get_test_post_trade_payload()
        payload["strategy_id"] = str(strategy_model.id)

    mock_execute_celery_buy_trade_task = AsyncMock(return_value="successfully added trade to db")
    monkeypatch.setattr(
        "app.api.endpoints.trading.execute_celery_buy_trade_task",
        mock_execute_celery_buy_trade_task,
    )

    response = await test_async_client.post("/api/trading/nfo/options", json=payload)

    assert response.status_code == 200
    assert response.json() == "successfully added trade to db"
    assert mock_execute_celery_buy_trade_task.called
