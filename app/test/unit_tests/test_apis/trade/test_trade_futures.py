import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.trade.IndianFNO.tasks import get_futures_profit
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
from app.test.utils import future_entry_price
from app.utils.constants import FUT
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
        assert trade_model.option_type == None  # noqa

        # expunge all trade models from session
        async_session.expunge_all()

        trade_models = [trade_model]
        # assert all trades are closed
        updated_values_dict = [
            getattr(trade_model, key)
            for key in update_trade_columns
            if key in futures_entry_columns_captured
            for trade_model in trade_models
        ]
        # all parameters of a trade are updated
        assert all(updated_values_dict)

        # assert trade in redis
        redis_trade_json = await test_async_redis_client.hget(
            f"{strategy_model.id}",
            f"{trade_model.expiry} {PositionEnum.LONG if action==SignalTypeEnum.BUY else PositionEnum.SHORT} {FUT}",
        )
        redis_trade_list = [
            RedisTradeSchema.model_validate_json(trade) for trade in json.loads(redis_trade_json)
        ]
        assert redis_trade_list == [RedisTradeSchema.model_validate(trade_model)]


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
        strategy_model = await async_session.scalar(
            select(StrategyModel).options(selectinload(StrategyModel.trades))
        )
        payload = get_test_post_trade_payload(action.value)
        payload["strategy_id"] = str(strategy_model.id)

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
            f"{trade_model.expiry} {PositionEnum.SHORT if action == SignalTypeEnum.BUY else PositionEnum.LONG} {FUT}",
            redis_trade_schema_list,
        )

        response = await test_async_client.post(trading_options_url, json=payload)

        assert response.status_code == 200
        assert response.json() == "successfully closed existing trades and bought a new trade"

        # expunge all trade models from session
        async_session.expunge_all()
        # fetch closed trades in db
        fetch_trade_models_query = await async_session.execute(
            select(TradeModel).filter(
                TradeModel.strategy_id == strategy_model.id,
                TradeModel.option_type == None,  # noqa
                TradeModel.future_exit_price_received != None,  # noqa
            )
        )
        exited_trade_models = fetch_trade_models_query.scalars().all()
        assert len(exited_trade_models) == 10

        # assert all trades are closed
        updated_values_dict = [
            getattr(trade_model, key)
            for key in update_trade_columns
            if key in futures_exit_columns_captured
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
            f"{exited_trade_models[0].expiry} {PositionEnum.LONG if action==SignalTypeEnum.BUY else PositionEnum.SHORT} {FUT}",
        )
        assert len(json.loads(redis_trade_list_json)) == 1
        # calculate profits
        option_chain = await get_option_chain(
            async_redis_client=test_async_redis_client,
            expiry=exited_trade_models[0].expiry,
            option_type=exited_trade_models[0].option_type,
            strategy_schema=StrategySchema.model_validate(strategy_model),
            is_future=True,
        )
        future_exit_price = float(option_chain.get(FUT))
        # entry price is fixed : 44315
        futures_profit = get_futures_profit(
            entry_price=future_entry_price,
            exit_price=future_exit_price,
            quantity=trade_model.quantity,
            signal=trade_model.action,
        )

        # when we short a trade then we make profit when exit price is lesser than 44315.0
        if future_exit_price < future_entry_price:
            assert futures_profit > 0
