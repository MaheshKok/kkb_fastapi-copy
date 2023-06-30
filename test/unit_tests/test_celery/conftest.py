import json
from datetime import datetime

import pytest_asyncio
from fastapi_sa.database import db
from sqlalchemy import select

from app.api.utils import get_current_and_next_expiry
from app.database.models import StrategyModel
from app.database.models import TradeModel
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from test.unit_tests.test_data import get_test_post_trade_payload
from test.utils import create_open_trades
from test.utils import create_pre_db_data


@pytest_asyncio.fixture(scope="function")
async def celery_buy_task_payload_dict(test_async_redis_client):
    post_trade_payload = get_test_post_trade_payload()

    await create_pre_db_data(users=1, strategies=1, trades=10)
    # query database for stragey

    async with db():
        fetch_strategy_query_ = await db.session.execute(select(StrategyModel))
        strategy_model = fetch_strategy_query_.scalars().one_or_none()

        (
            current_expiry_date,
            next_expiry_date,
            is_today_expiry,
        ) = await get_current_and_next_expiry(test_async_redis_client, datetime.now().date())

        post_trade_payload["strategy_id"] = strategy_model.id
        post_trade_payload["symbol"] = strategy_model.symbol
        post_trade_payload["expiry"] = current_expiry_date

        return post_trade_payload


async def celery_sell_task_args(test_async_redis_client, take_away_profit=False, ce_trade=False):
    await create_open_trades(
        users=1,
        strategies=1,
        trades=10,
        ce_trade=ce_trade,
        take_away_profit=take_away_profit,
    )
    post_trade_payload = get_test_post_trade_payload()

    async with db():
        # query database for stragey
        fetch_strategy_query_ = await db.session.execute(select(StrategyModel))
        strategy_model = fetch_strategy_query_.scalars().one_or_none()

        fetch_trade_query_ = await db.session.execute(select(TradeModel))
        trade_models = fetch_trade_query_.scalars().all()

        (
            current_expiry_date,
            next_expiry_date,
            is_today_expiry,
        ) = await get_current_and_next_expiry(test_async_redis_client, datetime.now().date())

        post_trade_payload["strategy_id"] = strategy_model.id
        post_trade_payload["symbol"] = strategy_model.symbol
        post_trade_payload["expiry"] = current_expiry_date
        post_trade_payload["option_type"] = "PE" if ce_trade else "CE"

        redis_key = f"{strategy_model.id} {trade_models[0].expiry} {trade_models[0].option_type}"
        redis_trades = [RedisTradeSchema.from_orm(trade).json() for trade in trade_models]

        await test_async_redis_client.lpush(redis_key, *redis_trades)
        return (
            strategy_model.id,
            SignalPayloadSchema(**post_trade_payload),
            redis_key,
            json.dumps(redis_trades),
        )
