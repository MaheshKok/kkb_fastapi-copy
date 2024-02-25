import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.trade.IndianFNO.tasks import get_futures_profit
from app.api.trade.IndianFNO.tasks import get_options_profit
from app.api.trade.IndianFNO.utils import get_current_and_next_expiry_from_redis
from app.api.trade.IndianFNO.utils import get_future_price_from_redis
from app.database.models import StrategyModel
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.test.unit_tests.test_apis.trade import trading_options_url
from app.test.unit_tests.test_data import get_test_post_trade_payload
from app.test.utils import create_close_trades
from app.test.utils import create_open_trades
from app.utils.constants import STRATEGY
from app.utils.constants import OptionType
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
async def test_trading_nfo_options_first_ever_trade_for_short_strategy(
    action, test_async_client, test_async_redis_client
):
    await create_close_trades(
        users=1,
        strategies=1,
        strategy_position=PositionEnum.SHORT,
        test_async_redis_client=test_async_redis_client,
    )

    async with Database() as async_session:
        strategy_model = await async_session.scalar(select(StrategyModel))
        payload = get_test_post_trade_payload(action.value)
        payload["strategy_id"] = str(strategy_model.id)

        # set strategy in redis
        await test_async_redis_client.hset(
            str(strategy_model.id),
            "strategy",
            StrategySchema.model_validate(strategy_model).model_dump_json(),
        )

        response = await test_async_client.post(trading_options_url, json=payload)

        assert response.status_code == 200
        assert response.json() == "successfully bought a new trade"

        # assert trade in db
        trade_model = await async_session.scalar(select(TradeModel))
        await async_session.refresh(strategy_model)
        assert trade_model.strategy_id == strategy_model.id
        assert (
            trade_model.option_type == OptionType.CE
            if action == SignalTypeEnum.SELL
            else OptionType.PE
        )

        # expunge all trade models from session
        async_session.expunge_all()

        trade_models = [trade_model]
        # assert all trades are closed
        updated_values_dict = [
            getattr(trade_model, key)
            for key in update_trade_columns
            if key in options_entry_columns_captured
            for trade_model in trade_models
        ]
        # all parameters of a trade are updated
        assert all(updated_values_dict)

        # assert trade in redis
        redis_trade_json = await test_async_redis_client.hget(
            f"{strategy_model.id}", f"{trade_model.expiry} {trade_model.option_type}"
        )
        redis_trade_list = [
            RedisTradeSchema.model_validate_json(trade) for trade in json.loads(redis_trade_json)
        ]
        assert redis_trade_list == [RedisTradeSchema.model_validate(trade_model)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", [SignalTypeEnum.BUY, SignalTypeEnum.SELL], ids=["Buy Signal", "Sell Signal"]
)
async def test_trading_nfo_options_opposite_direction_for_short_strategy(
    action, test_async_client, test_async_redis_client
):
    await create_open_trades(
        test_async_redis_client=test_async_redis_client,
        users=1,
        strategies=1,
        trades=10,
        ce_trade=action == SignalTypeEnum.BUY,
        position=PositionEnum.SHORT,
        action=SignalTypeEnum.BUY if action == SignalTypeEnum.SELL else SignalTypeEnum.SELL,
    )

    async with Database() as async_session:
        strategy_model = await async_session.scalar(
            select(StrategyModel).options(selectinload(StrategyModel.trades))
        )
        current_monthly_expiry, _, _ = await get_current_and_next_expiry_from_redis(
            async_redis_client=test_async_redis_client,
            instrument_type=InstrumentTypeEnum.FUTIDX,
            symbol=strategy_model.symbol,
        )
        future_exit_price = await get_future_price_from_redis(
            async_redis_client=test_async_redis_client,
            strategy_schema=StrategySchema.model_validate(strategy_model),
            expiry_date=current_monthly_expiry,
        )
        payload = get_test_post_trade_payload(action.value)
        payload["future_entry_price_received"] = str(future_exit_price)
        payload["strategy_id"] = str(strategy_model.id)

        old_funds = strategy_model.funds
        old_future_funds = strategy_model.future_funds

        # set strategy in redis
        await test_async_redis_client.hset(
            str(strategy_model.id),
            "strategy",
            StrategySchema.model_validate(strategy_model).model_dump_json(),
        )

        await async_session.refresh(strategy_model)

        # set trades in redis
        redis_trade_schema_list = json.dumps(
            [
                RedisTradeSchema.model_validate(trade).model_dump_json()
                for trade in strategy_model.trades
            ]
        )

        trade_model = strategy_model.trades[0]
        await test_async_redis_client.hset(
            f"{strategy_model.id}",
            f"{trade_model.expiry} {trade_model.option_type}",
            redis_trade_schema_list,
        )

        response = await test_async_client.post(trading_options_url, json=payload)

        assert response.status_code == 200
        assert response.json() == "successfully closed existing trades and bought a new trade"

        # expunge all trade models from session
        async_session.expunge_all()
        # fetch closed trades in db
        fetch_trade_models_query = await async_session.execute(
            select(TradeModel).filter_by(
                strategy_id=strategy_model.id,
                option_type=OptionType.CE if action == SignalTypeEnum.BUY else OptionType.PE,
            )
        )
        exited_trade_models = fetch_trade_models_query.scalars().all()
        assert len(exited_trade_models) == 10

        # assert all trades are closed
        updated_values_dict = [
            getattr(trade_model, key)
            for key in update_trade_columns
            if key in options_exit_columns_captured
            for trade_model in exited_trade_models
        ]
        # all parameters of a trade are updated
        assert all(updated_values_dict)

        # assert exiting trades are deleted from redis
        assert not await test_async_redis_client.hget(
            str(strategy_model.id),
            f"{exited_trade_models[0].expiry} {exited_trade_models[0].option_type}",
        )

        # assert new trade in redis
        redis_trade_list_json = await test_async_redis_client.hget(
            str(strategy_model.id),
            f"{exited_trade_models[0].expiry} {OptionType.CE if action == SignalTypeEnum.SELL else OptionType.PE}",
        )
        assert len(json.loads(redis_trade_list_json)) == 1

        # assert strategy funds are updated
        strategy_query = await async_session.execute(
            select(StrategyModel).filter_by(id=strategy_model.id)
        )
        strategy_model = strategy_query.scalars().one_or_none()
        strategy_json = await test_async_redis_client.hget(str(strategy_model.id), STRATEGY)
        redis_strategy_schema = StrategySchema.model_validate_json(strategy_json)

        actual_total_profit = sum(trade_model.profit for trade_model in exited_trade_models)
        actual_future_profit = sum(
            trade_model.future_profit for trade_model in exited_trade_models
        )
        trade_model = exited_trade_models[0]
        option_chain = await get_option_chain(
            async_redis_client=test_async_redis_client,
            expiry=trade_model.expiry,
            strategy_schema=redis_strategy_schema,
            option_type=trade_model.option_type,
        )
        exit_price = option_chain.get(trade_model.strike)
        expected_total_profit = 0
        expected_future_profit = 0
        for trade_model in exited_trade_models:
            expected_total_profit += get_options_profit(
                entry_price=trade_model.entry_price,
                exit_price=exit_price,
                quantity=trade_model.quantity,
                position=redis_strategy_schema.position,
            )
            expected_future_profit += get_futures_profit(
                entry_price=trade_model.future_entry_price_received,
                exit_price=future_exit_price,
                quantity=trade_model.quantity,
                # reason being existing trade has the action opposite to the current signal
                signal=(
                    SignalTypeEnum.SELL if action == SignalTypeEnum.BUY else SignalTypeEnum.BUY
                ),
            )

        assert expected_total_profit == actual_total_profit
        assert expected_future_profit == actual_future_profit
        assert redis_strategy_schema.funds == old_funds + actual_total_profit
        assert redis_strategy_schema.future_funds == old_future_funds + actual_future_profit
        assert strategy_model.funds == old_funds + actual_total_profit
        assert strategy_model.future_funds == old_future_funds + actual_future_profit
