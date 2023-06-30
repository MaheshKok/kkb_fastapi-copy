import json

import httpx
import pytest
from fastapi_sa.database import db
from sqlalchemy import select
from tasks.execution import task_entry_trade

from app.database.models import TradeModel
from app.database.models.strategy import StrategyModel
from app.schemas.strategy import StrategySchema
from app.schemas.trade import SignalPayloadSchema


# I just fixed them , but didnt assert so many things


@pytest.mark.asyncio
@pytest.mark.parametrize("option_type", ["CE", "PE"], ids=["CE Options", "PE Options"])
async def test_buy_trade_for_premium_and_add_trades_to_new_key_in_redis(
    option_type, celery_buy_task_payload_dict, test_async_redis_client
):
    if option_type == "PE":
        celery_buy_task_payload_dict["option_type"] = "PE"

    async with db():
        strategy_model = await db.session.get(
            StrategyModel, celery_buy_task_payload_dict["strategy_id"]
        )
        strategy_schema = StrategySchema.from_orm(strategy_model)
        await task_entry_trade(
            signal_payload_schema=SignalPayloadSchema(**celery_buy_task_payload_dict),
            async_redis_client=test_async_redis_client,
            strategy_schema=strategy_schema,
            async_httpx_client=httpx.AsyncClient(),
        )
        fetch_trades_query_ = await db.session.execute(
            select(TradeModel).order_by(TradeModel.entry_at.desc())
        )
        trades = fetch_trades_query_.scalars().all()
        assert len(trades) == 11
        trade_model = trades[0]

        strategy_model = await db.session.scalar(select(StrategyModel))

        assert trade_model.strategy.id == strategy_model.id
        assert trade_model.entry_price <= celery_buy_task_payload_dict["premium"]
        key = f"{strategy_model.id} {trade_model.expiry} {trade_model.option_type}"
        redis_in_trades_list = await test_async_redis_client.lrange(key, 0, -1)
        assert len(redis_in_trades_list) == 1
        assert json.loads(redis_in_trades_list[0])["id"] == str(trade_model.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("option_type", ["CE", "PE"], ids=["CE Options", "PE Options"])
async def test_buy_trade_for_premium_and_add_trade_to_ongoing_trades_in_redis(
    test_async_redis_client, option_type, celery_buy_task_payload_dict
):
    if option_type == "PE":
        celery_buy_task_payload_dict["option_type"] = "PE"

    # We dont need to create closed trades here explicitly
    # because get_test_celery_buy_task_payload_dict already takes care of it

    async with db():
        strategy_model = await db.session.get(
            StrategyModel, celery_buy_task_payload_dict["strategy_id"]
        )
        strategy_schema = StrategySchema.from_orm(strategy_model)
        await task_entry_trade(
            signal_payload_schema=SignalPayloadSchema(**celery_buy_task_payload_dict),
            async_redis_client=test_async_redis_client,
            strategy_schema=strategy_schema,
            async_httpx_client=httpx.AsyncClient(),
        )

        # the top most trade is the one which is just created
        fetch_trades_query_ = await db.session.execute(
            select(TradeModel).order_by(TradeModel.entry_at.desc())
        )
        trades = fetch_trades_query_.scalars().all()
        assert len(trades) == 11
        trade_model = trades[0]

        strategy_model = await db.session.scalar(select(StrategyModel))

        assert trade_model.strategy.id == strategy_model.id
        assert trade_model.entry_price <= celery_buy_task_payload_dict["premium"]

        # trades are being added to redis
        key = f"{strategy_model.id} {trade_model.expiry} {trade_model.option_type}"
        redis_in_trades_list = await test_async_redis_client.lrange(key, 0, -1)
        assert len(redis_in_trades_list) == 1
        assert json.loads(redis_in_trades_list[0])["id"] == str(trade_model.id)


@pytest.mark.parametrize(
    "payload_strike", ["43500.0", "43510.0"], ids=["valid strike", "invalid strike"]
)
@pytest.mark.asyncio
async def test_buy_trade_for_strike(
    payload_strike, test_async_redis_client, celery_buy_task_payload_dict
):
    del celery_buy_task_payload_dict["premium"]
    celery_buy_task_payload_dict["strike"] = payload_strike

    # We dont need to create closed trades here explicitly
    # because get_test_celery_buy_task_payload_dict already takes care of it

    async with db():
        strategy_model = await db.session.get(
            StrategyModel, celery_buy_task_payload_dict["strategy_id"]
        )
        strategy_schema = StrategySchema.from_orm(strategy_model)
        await task_entry_trade(
            signal_payload_schema=SignalPayloadSchema(**celery_buy_task_payload_dict),
            async_redis_client=test_async_redis_client,
            strategy_schema=strategy_schema,
            async_httpx_client=httpx.AsyncClient(),
        )

        # the top most trade is the one which is just created
        fetch_trades_query_ = await db.session.execute(
            select(TradeModel).order_by(TradeModel.entry_at.desc())
        )
        trade_model_list = fetch_trades_query_.scalars().all()
        assert len(trade_model_list) == 11
        trade_model = trade_model_list[0]

        # query database for stragey
        strategy_model = await db.session.scalar(select(StrategyModel))

        assert trade_model.strategy.id == strategy_model.id
        assert trade_model.strike <= float(payload_strike)

        key = f"{strategy_model.id} {trade_model.expiry} {trade_model.option_type}"
        redis_in_trades_list = await test_async_redis_client.lrange(key, 0, -1)
        assert len(redis_in_trades_list) == 1
        assert json.loads(redis_in_trades_list[0])["id"] == str(trade_model.id)
