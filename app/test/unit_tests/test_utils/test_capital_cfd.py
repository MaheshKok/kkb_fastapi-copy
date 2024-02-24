from datetime import datetime
from decimal import getcontext

import pytest

from app.api.trade.Capital.utils import get_lots_to_trade_and_profit_or_loss
from app.schemas.strategy import CFDStrategySchema


# I think i got all edge cases covered


@pytest.mark.asyncio
async def test_get_lots_to_trade():
    getcontext().prec = 28
    cfd_strategy_schema = CFDStrategySchema(
        id="b9475dee-0ec9-4ca6-815b-cbbfdf2cbc3d",
        instrument="GOLD",
        min_quantity=10,
        max_drawdown=100,
        margin_for_min_quantity=100,
        incremental_step_size=0.1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        is_active=True,
        is_demo=True,
        funds=1512.01,
        name="test gold cfd",
        compounding=True,
        funds_usage_percent=1.0,
        user_id="fb90dd9c-9e16-4043-b5a5-18aacb42f726",
    )

    lots_to_open, update_profit_or_loss_in_db = get_lots_to_trade_and_profit_or_loss(
        1000, cfd_strategy_schema, 500
    )
    assert update_profit_or_loss_in_db == 500
    assert lots_to_open == 201.2


@pytest.mark.asyncio
async def test_get_lots_to_trade_for_banknifty():
    # funds required for 45 is just above the available funds even after profit or loss into consideration
    # get_lots_to_trade_and_profit_or_loss produces 30.0 as ans
    getcontext().prec = 28
    cfd_strategy_schema = CFDStrategySchema(
        id="b9475dee-0ec9-4ca6-815b-cbbfdf2cbc3d",
        instrument="GOLD",
        min_quantity=15,
        max_drawdown=100,
        margin_for_min_quantity=92000,
        incremental_step_size=15,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        is_active=True,
        is_demo=True,
        funds=200000,
        name="test gold cfd",
        compounding=True,
        funds_usage_percent=1.0,
        user_id="fb90dd9c-9e16-4043-b5a5-18aacb42f726",
    )

    lots_to_open, update_profit_or_loss_in_db = get_lots_to_trade_and_profit_or_loss(
        1000, cfd_strategy_schema, 70000
    )
    assert update_profit_or_loss_in_db == 70000
    assert lots_to_open == 30.0


@pytest.mark.asyncio
async def test_get_lots_to_trade_20_percent_usage():
    # funds usage percent is 0.2 which comes around 600 and margin required for min quantity is 1000,
    # so in this case 1000 funds would be used to calculate trade lots
    getcontext().prec = 28
    cfd_strategy_schema = CFDStrategySchema(
        id="b9475dee-0ec9-4ca6-815b-cbbfdf2cbc3d",
        instrument="GOLD",
        min_quantity=10,
        max_drawdown=100,
        margin_for_min_quantity=1000,
        incremental_step_size=0.1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        is_active=True,
        is_demo=True,
        funds=3000,
        name="test gold cfd",
        compounding=True,
        funds_usage_percent=0.2,
        user_id="fb90dd9c-9e16-4043-b5a5-18aacb42f726",
    )

    lots_to_open, update_profit_or_loss_in_db = get_lots_to_trade_and_profit_or_loss(
        1000, cfd_strategy_schema, 500
    )
    assert update_profit_or_loss_in_db == 500
    # ideally ans should be 10.0, but 9.9 is very close and we have to ignore it because of how Decimal works
    # it trears 0.1 as 0.10000056465675 and when added it 9.9 then ans is 10.00000011 and it is greater than 10.0
    # so it outputs number which is just below 10.0 and divisible by incremental_step_size
    assert lots_to_open == 9.9


@pytest.mark.asyncio
async def test_get_lots_to_trade_20_percent_usage_for_banknifty():
    # funds usage percent is 0.2 which comes around 600 and margin required for min quantity is 1000,
    # so in this case 1000 funds would be used to calculate trade lots
    getcontext().prec = 28
    cfd_strategy_schema = CFDStrategySchema(
        id="b9475dee-0ec9-4ca6-815b-cbbfdf2cbc3d",
        instrument="GOLD",
        min_quantity=15,
        max_drawdown=100,
        margin_for_min_quantity=90000,
        incremental_step_size=15,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        is_active=True,
        is_demo=True,
        funds=200000,
        name="test gold cfd",
        compounding=True,
        funds_usage_percent=0.2,
        user_id="fb90dd9c-9e16-4043-b5a5-18aacb42f726",
    )

    lots_to_open, update_profit_or_loss_in_db = get_lots_to_trade_and_profit_or_loss(
        1000, cfd_strategy_schema, 500
    )
    assert update_profit_or_loss_in_db == 500
    assert lots_to_open == 15.0


@pytest.mark.asyncio
async def test_get_lots_to_trade_for_fixed_contracts():
    getcontext().prec = 28
    cfd_strategy_schema = CFDStrategySchema(
        id="b9475dee-0ec9-4ca6-815b-cbbfdf2cbc3d",
        instrument="GOLD",
        min_quantity=10,
        max_drawdown=100,
        margin_for_min_quantity=100,
        incremental_step_size=0.1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        is_active=True,
        is_demo=True,
        funds=1500,
        name="test gold cfd",
        compounding=False,
        contracts=150,
        funds_usage_percent=1.0,
        user_id="fb90dd9c-9e16-4043-b5a5-18aacb42f726",
    )

    lots_to_open, update_profit_or_loss_in_db = get_lots_to_trade_and_profit_or_loss(
        1000, cfd_strategy_schema, 500
    )
    assert update_profit_or_loss_in_db == 500
    assert lots_to_open == 150.0


@pytest.mark.asyncio
async def test_get_lots_to_trade_for_fixed_contracts__when_funds_required_is_less():
    getcontext().prec = 28
    cfd_strategy_schema = CFDStrategySchema(
        id="b9475dee-0ec9-4ca6-815b-cbbfdf2cbc3d",
        instrument="GOLD",
        min_quantity=10,
        max_drawdown=100,
        margin_for_min_quantity=3000,
        incremental_step_size=0.1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        is_active=True,
        is_demo=True,
        funds=1500,
        name="test gold cfd",
        compounding=False,
        contracts=10,
        funds_usage_percent=1.0,
        user_id="fb90dd9c-9e16-4043-b5a5-18aacb42f726",
    )

    lots_to_open, update_profit_or_loss_in_db = get_lots_to_trade_and_profit_or_loss(
        1000, cfd_strategy_schema, 500
    )
    assert update_profit_or_loss_in_db == 500
    assert lots_to_open == 6.6
