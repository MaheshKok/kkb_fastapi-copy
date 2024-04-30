import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.trade.IndianFNO.utils import get_current_and_next_expiry_from_redis
from app.api.trade.IndianFNO.utils import get_future_price_from_redis
from app.api.trade.IndianFNO.utils import get_futures_profit
from app.database.schemas import StrategyDBModel
from app.database.schemas import TradeDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.enums import InstrumentTypeEnum
from app.pydantic_models.enums import PositionEnum
from app.pydantic_models.enums import SignalTypeEnum
from app.pydantic_models.strategy import StrategyPydanticModel
from app.pydantic_models.trade import RedisTradePydanticModel
from app.test.unit_tests.test_apis.trade import trading_options_url
from app.test.unit_tests.test_data import get_test_post_trade_payload
from app.test.utils import create_close_trades
from app.test.utils import create_open_trades
from app.utils.constants import FUT
from app.utils.constants import STRATEGY
from app.utils.constants import update_trade_columns
from app.utils.option_chain import get_option_chain


futures_entry_columns_captured = {
    "instrument",
    "quantity",
    "entry_price",
    "future_entry_price_received",
    "entry_priceceived_at",
    "entry_at",
    "expiry",
    "action",
    "strategy_id",
}
options_specific_entry_columns = {"strike", "option_type"}
options_entry_columns_captured = {
    *futures_entry_columns_captured,
    *options_specific_entry_columns,
}

exit_columns_captured = futures_exit_columns_captured = {
    *futures_entry_columns_captured,
    "exit_price",
    "future_exit_price_received",
    "exit_received_at",
    "exit_at",
    "profit",
    "future_profit",
}
options_exit_columns_captured = {*options_entry_columns_captured, *exit_columns_captured}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", [SignalTypeEnum.BUY, SignalTypeEnum.SELL], ids=["Buy Signal", "Sell Signal"]
)
async def test_trading_nfo_futures_first_ever_trade(
    action, test_async_client, test_async_redis_client
):
    await create_close_trades(
        users=1,
        strategies=1,
        strategy_position=PositionEnum.LONG,
        instrument_type=InstrumentTypeEnum.FUTIDX,
        test_async_redis_client=test_async_redis_client,
    )

    async with Database() as async_session:
        strategy_db_model = await async_session.scalar(select(StrategyDBModel))
        payload = get_test_post_trade_payload(action.value)
        payload["strategy_id"] = str(strategy_db_model.id)

        # set strategy in redis
        await test_async_redis_client.hset(
            str(strategy_db_model.id),
            "strategy",
            StrategyPydanticModel.model_validate(strategy_db_model).model_dump_json(),
        )

        response = await test_async_client.post(trading_options_url, json=payload)

        assert response.status_code == 200
        assert response.json() == "successfully bought a new trade"

        # assert trade in db
        trade_db_model = await async_session.scalar(select(TradeDBModel))
        await async_session.refresh(strategy_db_model)
        assert trade_db_model.strategy_id == strategy_db_model.id
        assert trade_db_model.option_type == None  # noqa

        # expunge all trade schemas from session
        async_session.expunge_all()

        trade_db_models = [trade_db_model]
        # assert all trades are closed
        updated_values_dict = [
            getattr(trade_db_model, key)
            for key in update_trade_columns
            if key in futures_entry_columns_captured
            for trade_db_model in trade_db_models
        ]
        # all parameters of a trade are updated
        assert all(updated_values_dict)

        # assert trade in redis
        redis_trade_json = await test_async_redis_client.hget(
            f"{strategy_db_model.id}",
            f"{trade_db_model.expiry} {PositionEnum.LONG if action==SignalTypeEnum.BUY else PositionEnum.SHORT} {FUT}",
        )
        redis_trade_list = [
            RedisTradePydanticModel.model_validate_json(trade)
            for trade in json.loads(redis_trade_json)
        ]
        assert redis_trade_list == [RedisTradePydanticModel.model_validate(trade_db_model)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", [SignalTypeEnum.BUY, SignalTypeEnum.SELL], ids=["Buy Signal", "Sell Signal"]
)
async def test_trading_nfo_futures_opposite_direction(
    action, test_async_client, test_async_redis_client
):
    await create_open_trades(
        test_async_redis_client=test_async_redis_client,
        users=1,
        strategies=1,
        trades=10,
        position=PositionEnum.LONG,
        instrument_type=InstrumentTypeEnum.FUTIDX,
        action=SignalTypeEnum.BUY if action == SignalTypeEnum.SELL else SignalTypeEnum.SELL,
    )

    async with Database() as async_session:
        strategy_db_model = await async_session.scalar(
            select(StrategyDBModel).options(selectinload(StrategyDBModel.trades))
        )
        current_monthly_expiry, _, _ = await get_current_and_next_expiry_from_redis(
            async_redis_client=test_async_redis_client,
            instrument_type=InstrumentTypeEnum.FUTIDX,
            symbol=strategy_db_model.symbol,
        )
        future_exit_price = await get_future_price_from_redis(
            async_redis_client=test_async_redis_client,
            strategy_pyd_model=StrategyPydanticModel.model_validate(strategy_db_model),
            expiry_date=current_monthly_expiry,
        )
        payload = get_test_post_trade_payload(action.value)
        payload["future_entry_price_received"] = str(future_exit_price)
        payload["strategy_id"] = str(strategy_db_model.id)

        old_funds = strategy_db_model.funds
        old_future_funds = strategy_db_model.future_funds

        # set strategy in redis
        await test_async_redis_client.hset(
            str(strategy_db_model.id),
            "strategy",
            StrategyPydanticModel.model_validate(strategy_db_model).model_dump_json(),
        )

        await async_session.refresh(strategy_db_model)

        # set trades in redis
        redis_trade_pyd_model_list = json.dumps(
            [
                RedisTradePydanticModel.model_validate(trade).model_dump_json()
                for trade in strategy_db_model.trades
            ]
        )

        trade_db_model = strategy_db_model.trades[0]
        await test_async_redis_client.hset(
            f"{strategy_db_model.id}",
            f"{trade_db_model.expiry} {PositionEnum.SHORT if action == SignalTypeEnum.BUY else PositionEnum.LONG} {FUT}",
            redis_trade_pyd_model_list,
        )

        response = await test_async_client.post(trading_options_url, json=payload)

        assert response.status_code == 200
        assert response.json() == "successfully closed existing trades and bought a new trade"

        # expunge all trade schemas from session
        async_session.expunge_all()
        # fetch closed trades in db
        fetch_trade__query = await async_session.execute(
            select(TradeDBModel).filter(
                TradeDBModel.strategy_id == strategy_db_model.id,
                TradeDBModel.option_type == None,  # noqa
                TradeDBModel.future_exit_price_received != None,  # noqa
            )
        )
        exited_trade_db_models = fetch_trade__query.scalars().all()
        assert len(exited_trade_db_models) == 10

        # assert all trades are closed
        updated_values_dict = [
            getattr(trade_db_model, key)
            for key in update_trade_columns
            if key in futures_exit_columns_captured
            for trade_db_model in exited_trade_db_models
        ]
        # all parameters of a trade are updated
        assert all(updated_values_dict)

        # assert exiting trades are deleted from redis
        assert not await test_async_redis_client.hget(
            str(strategy_db_model.id),
            f"{exited_trade_db_models[0].expiry} {exited_trade_db_models[0].option_type}",
        )

        # assert new trade in redis
        redis_trade_list_json = await test_async_redis_client.hget(
            str(strategy_db_model.id),
            f"{exited_trade_db_models[0].expiry} {PositionEnum.LONG if action==SignalTypeEnum.BUY else PositionEnum.SHORT} {FUT}",
        )
        assert len(json.loads(redis_trade_list_json)) == 1

        # assert strategy funds are updated
        strategy_query = await async_session.execute(
            select(StrategyDBModel).filter_by(id=strategy_db_model.id)
        )
        strategy_db_model = strategy_query.scalars().one_or_none()
        strategy_json = await test_async_redis_client.hget(str(strategy_db_model.id), STRATEGY)
        redis_strategy_pyd_model = StrategyPydanticModel.model_validate_json(strategy_json)

        actual_total_profit = round(
            sum(trade_db_model.profit for trade_db_model in exited_trade_db_models), 2
        )
        actual_future_profit = round(
            sum(trade_db_model.future_profit for trade_db_model in exited_trade_db_models), 2
        )
        trade_db_model = exited_trade_db_models[0]
        option_chain = await get_option_chain(
            async_redis_client=test_async_redis_client,
            expiry=trade_db_model.expiry,
            strategy_pyd_model=redis_strategy_pyd_model,
            is_future=True,
        )
        exit_price = float(option_chain.get("FUT"))
        expected_total_profit = 0
        expected_future_profit = 0
        for trade_db_model in exited_trade_db_models:
            expected_total_profit += get_futures_profit(
                entry_price=trade_db_model.entry_price,
                exit_price=exit_price,
                quantity=trade_db_model.quantity,
                signal=(
                    SignalTypeEnum.SELL if action == SignalTypeEnum.BUY else SignalTypeEnum.BUY
                ),
            )
            expected_future_profit += get_futures_profit(
                entry_price=trade_db_model.future_entry_price_received,
                exit_price=future_exit_price,
                quantity=trade_db_model.quantity,
                # reason being existing trade has the action opposite to the current signal
                signal=(
                    SignalTypeEnum.SELL if action == SignalTypeEnum.BUY else SignalTypeEnum.BUY
                ),
            )

        expected_total_profit = round(expected_total_profit, 2)
        expected_future_profit = round(expected_future_profit, 2)
        assert expected_total_profit == actual_total_profit
        assert expected_future_profit == actual_future_profit
        assert redis_strategy_pyd_model.funds == old_funds + actual_total_profit
        assert redis_strategy_pyd_model.future_funds == old_future_funds + actual_future_profit
        assert strategy_db_model.funds == old_funds + actual_total_profit
        assert strategy_db_model.future_funds == old_future_funds + actual_future_profit
