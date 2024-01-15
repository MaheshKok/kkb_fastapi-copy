from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.api.utils import get_capital_cfd_lot_to_trade
from app.schemas.strategy import CFDStrategySchema


@pytest.mark.asyncio
async def test_get_capital_cfd_lot_to_trade(monkeypatch):
    monkeypatch.setattr(
        "app.api.utils.get_funds_to_use",
        AsyncMock(return_value=Decimal("10000")),
    )
    cfd_strategy_schema = CFDStrategySchema(
        id="b9475dee-0ec9-4ca6-815b-cbbfdf2cbc3d",
        instrument="GOLD",
        min_quantity=1,
        max_drawdown=100,
        margin_for_min_quantity=80,
        incremental_step_size=0.1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        is_active=True,
        is_demo=True,
        funds=4000,
        name="test gold cfd",
        compounding=True,
        funds_usage_percent=1.0,
        user_id="fb90dd9c-9e16-4043-b5a5-18aacb42f726",
    )
    result = await get_capital_cfd_lot_to_trade(
        None,
        cfd_strategy_schema,
        600,
    )
    assert result == 18.7
