from uuid import UUID

import pytest
from sqlalchemy import select

from app.database.models import StrategyModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.strategy import StrategyCreateSchema
from app.test.factory.strategy import StrategyFactory
from app.test.factory.user import UserFactory


@pytest.mark.asyncio
async def test_get_empty_strategys(test_async_client):
    response = await test_async_client.get("/api/strategy")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_strategys(test_async_client):
    # create a strategy
    user = await UserFactory()
    for _ in range(10):
        await StrategyFactory(user=user)

    async with Database() as async_session:
        strategy_query = await async_session.scalars(select(StrategyModel.id, StrategyModel))
        strategy_ids = strategy_query.all()

        response = await test_async_client.get("/api/strategy")
        assert response.status_code == 200
        assert all(UUID(strategy_data["id"]) in strategy_ids for strategy_data in response.json())


@pytest.mark.asyncio
async def test_post_strategys(test_async_client):
    # create a strategy
    user = await UserFactory()

    async with Database() as async_session:
        strategy_query = await async_session.scalars(select(StrategyModel.id, StrategyModel))
        strategy_ids = strategy_query.all()
        assert len(strategy_ids) == 0

        strategy_payload = StrategyCreateSchema(
            instrument_type=InstrumentTypeEnum.OPTIDX,
            symbol="BANKNIFTY",
            name="BANKNIFTY1! TF:2 Brick_Size:35 Pyramiding:100",
            position=PositionEnum.LONG,
            premium=350.0,
            funds=1000000.0,
            min_quantity=10,
            margin_for_min_quantity=2.65,
            incremental_step_size=0.1,
            compounding=True,
            contracts=15,
            funds_usage_percent=0.25,
            user_id=user.id,
        )
        response = await test_async_client.post(
            "/api/strategy", data=strategy_payload.model_dump_json()
        )
        assert response.status_code == 200
        del response.json()["id"]
        assert StrategyCreateSchema(**response.json()) == strategy_payload
