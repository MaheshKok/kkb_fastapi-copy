from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import Select

from app.api.utils import get_current_and_next_expiry
from app.database.models import StrategyModel
from test.conftest import create_closed_trades
from test.unit_tests.test_data import get_test_post_trade_payload


@pytest.mark.asyncio
@pytest_asyncio.fixture(scope="function")
async def get_task_trade_payload(test_async_session, test_async_redis):
    post_trade_payload = get_test_post_trade_payload()

    await create_closed_trades(test_async_session, users=1, strategies=1, trades=10)
    # query database for stragey

    fetch_strategy_query_ = await test_async_session.execute(Select(StrategyModel))
    strategy_model = fetch_strategy_query_.scalars().one_or_none()

    current_expiry_date, next_expiry_date, is_today_expiry = await get_current_and_next_expiry(
        test_async_redis, datetime.now().date()
    )

    post_trade_payload["entry_received_at"] = post_trade_payload.pop("received_at")
    post_trade_payload["strategy_id"] = strategy_model.id
    post_trade_payload["symbol"] = strategy_model.symbol
    post_trade_payload["expiry"] = current_expiry_date

    return post_trade_payload
