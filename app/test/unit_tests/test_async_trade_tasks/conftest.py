import json
from datetime import datetime

from sqlalchemy import select

from app.api.utils import get_current_and_next_expiry_from_redis
from app.database.models import StrategyModel
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.trade import RedisTradeSchema
from app.schemas.trade import SignalPayloadSchema
from app.test.unit_tests.test_data import get_test_post_trade_payload
from app.test.utils import create_open_trades


async def sell_task_args(test_async_redis_client, take_away_profit=False, ce_trade=False):
    await create_open_trades(
        users=1,
        strategies=1,
        trades=10,
        ce_trade=ce_trade,
        take_away_profit=take_away_profit,
    )
    post_trade_payload = get_test_post_trade_payload()

    async with Database() as async_session:
        # query database for stragey
        fetch_strategy_query_ = await async_session.execute(select(StrategyModel))
        strategy_model = fetch_strategy_query_.scalars().one_or_none()

        fetch_trade_query_ = await async_session.execute(select(TradeModel))
        trade_models = fetch_trade_query_.scalars().all()

        (
            current_expiry_date,
            next_expiry_date,
            is_today_expiry,
        ) = await get_current_and_next_expiry_from_redis(
            test_async_redis_client, datetime.now().date()
        )

        post_trade_payload["strategy_id"] = strategy_model.id
        post_trade_payload["symbol"] = strategy_model.symbol
        post_trade_payload["expiry"] = current_expiry_date
        post_trade_payload["option_type"] = "PE" if ce_trade else "CE"

        redis_trade_schema_list = [
            RedisTradeSchema.model_validate(trade) for trade in trade_models
        ]

        redis_trade_key_hash = (
            f"{strategy_model.id} {trade_models[0].expiry} {trade_models[0].option_type}"
        )

        await test_async_redis_client.hset(
            redis_trade_key_hash.split()[0],
            redis_trade_key_hash.split()[1],
            json.dumps([trade.model_dump_json() for trade in redis_trade_schema_list]),
        )
        return (
            strategy_model.id,
            SignalPayloadSchema(**post_trade_payload),
            redis_trade_key_hash,
            redis_trade_schema_list,
        )
