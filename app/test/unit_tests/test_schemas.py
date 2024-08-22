import pytest

from app.pydantic_models.strategy import StrategyCreatePydModel


strategy_payload = {
    "instrument_type": "FUTIDX",
    "symbol": "BANKNIFTY",
    "name": "BANKNIFTY1! TF:5 Brick_Size:83",
    "only_on_expiry": False,
    "position": "SHORT",
    "premium": 700.0,
    "funds": 200000.0,
    "future_funds": 200000.0,
    "min_quantity": 15.0,
    "margin_for_min_quantity": 95000,
    "incremental_step_size": 15,
    "compounding": True,
    "contracts": 15.0,
    "funds_usage_percent": 0.5,
    "broker_id": None,
    "user_id": "fb90dd9c-9e16-4043-b5a5-18aacb42f726",
}


@pytest.mark.asyncio
async def test_strategy_compounding_results_in_0_contracts():
    strategy_payload["compounding"] = True
    strategy_pyd_model = StrategyCreatePydModel(**strategy_payload)
    assert strategy_pyd_model.contracts == 0.0


@pytest.mark.asyncio
async def test_strategy_futidx_results_in_0_premium():
    strategy_pyd_model = StrategyCreatePydModel(**strategy_payload)
    assert strategy_pyd_model.premium == 0.0


@pytest.mark.asyncio
async def test_strategy_optidx_raise_error_for_no_premium():
    strategy_payload["instrument_type"] = "OPTIDX"
    del strategy_payload["premium"]
    with pytest.raises(ValueError):
        StrategyCreatePydModel(**strategy_payload)


@pytest.mark.asyncio
async def test_strategy_not_compounding_raise_error_for_no_contracts():
    strategy_payload["compounding"] = False
    del strategy_payload["contracts"]
    with pytest.raises(ValueError):
        StrategyCreatePydModel(**strategy_payload)
