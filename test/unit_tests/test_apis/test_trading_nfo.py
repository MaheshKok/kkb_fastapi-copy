import pytest
from fastapi_sa.database import db
from sqlalchemy import select

from app.database.models import StrategyModel
from app.schemas.strategy import StrategySchema
from test.unit_tests.test_data import get_test_post_trade_payload
from test.utils import create_pre_db_data


@pytest.mark.asyncio
async def test_trading_nfo_options_with_valid_strategy_id(test_async_client, test_app):
    await create_pre_db_data(users=1, strategies=1)

    async with db():
        strategy_model = await db.session.scalar(select(StrategyModel))
        payload = get_test_post_trade_payload()
        payload["strategy_id"] = str(strategy_model.id)
        await test_app.state.async_redis_client.set(
            str(strategy_model.id), StrategySchema.from_orm(strategy_model).json()
        )

    response = await test_async_client.post("/api/trading/nfo/options", json=payload)

    assert response.status_code == 200
    assert response.json() == "successfully added trade to db"
