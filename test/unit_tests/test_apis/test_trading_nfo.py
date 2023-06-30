import pytest
from fastapi_sa.database import db
from sqlalchemy import select

from app.database.models import StrategyModel
from app.database.models import TradeModel
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from test.unit_tests.test_data import get_test_post_trade_payload
from test.utils import create_open_trades
from test.utils import create_pre_db_data


@pytest.mark.asyncio
@pytest.mark.parametrize("option_type", ["CE", "PE"], ids=["CE Options", "PE Options"])
async def test_trading_nfo_options_with_no_existing_trades(
    option_type, test_async_client, test_async_redis_client
):
    await create_pre_db_data(users=1, strategies=1)

    async with db():
        strategy_model = await db.session.scalar(select(StrategyModel))
        payload = get_test_post_trade_payload()
        payload["strategy_id"] = str(strategy_model.id)

        if option_type == "PE":
            payload["option_type"] = "PE"

        # set strategy in redis
        await test_async_redis_client.set(
            str(strategy_model.id), StrategySchema.from_orm(strategy_model).json()
        )

        response = await test_async_client.post("/api/trading/nfo/options", json=payload)

        assert response.status_code == 200
        assert response.json() == "successfully added trade to db"

        # assert trade in db
        trade_model = await db.session.scalar(select(TradeModel))
        await db.session.refresh(strategy_model)
        assert trade_model.strategy_id == strategy_model.id

        # assert trade in redis
        redis_trade_list_json = await test_async_redis_client.lrange(
            f"{strategy_model.id} {trade_model.expiry} {trade_model.option_type}", 0, -1
        )
        redis_trade_list = [RedisTradeSchema.parse_raw(trade) for trade in redis_trade_list_json]
        assert redis_trade_list == [RedisTradeSchema.from_orm(trade_model)]


@pytest.mark.asyncio
@pytest.mark.parametrize("option_type", ["CE", "PE"], ids=["CE Options", "PE Options"])
async def test_trading_nfo_options_with_existing_trade_of_same_type(
    option_type, test_async_client, test_async_redis_client
):
    await create_open_trades(users=1, strategies=1, trades=10, ce_trade=option_type == "CE")

    async with db():
        strategy_model = await db.session.scalar(select(StrategyModel))
        payload = get_test_post_trade_payload()
        payload["strategy_id"] = str(strategy_model.id)

        if option_type == "PE":
            payload["option_type"] = "PE"

        # set strategy in redis
        await test_async_redis_client.set(
            str(strategy_model.id), StrategySchema.from_orm(strategy_model).json()
        )

        # set trades in redis
        fetch_trade_models_query = await db.session.execute(
            select(TradeModel).filter_by(strategy_id=strategy_model.id)
        )
        trade_models = fetch_trade_models_query.scalars().all()
        for trade_model in trade_models:
            await test_async_redis_client.rpush(
                f"{strategy_model.id} {trade_model.expiry} {trade_model.option_type}",
                RedisTradeSchema.from_orm(trade_model).json(),
            )

        response = await test_async_client.post("/api/trading/nfo/options", json=payload)

        assert response.status_code == 200
        assert response.json() == "successfully added trade to db"

        # assert trade in db
        await db.session.refresh(strategy_model)
        fetch_trade_models_query = await db.session.execute(
            select(TradeModel).filter_by(strategy_id=strategy_model.id)
        )
        trade_models = fetch_trade_models_query.scalars().all()
        assert len(trade_models) == 11

        # assert trade in redis
        redis_trade_list_json = await test_async_redis_client.lrange(
            f"{strategy_model.id} {trade_models[0].expiry} {trade_models[0].option_type}", 0, -1
        )
        assert len(redis_trade_list_json) == 11

        redis_trade_list = [RedisTradeSchema.parse_raw(trade) for trade in redis_trade_list_json]
        assert redis_trade_list == [
            RedisTradeSchema.from_orm(trade_model) for trade_model in trade_models
        ]
