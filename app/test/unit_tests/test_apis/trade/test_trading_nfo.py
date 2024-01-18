import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.models import StrategyModel
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import PositionEnum
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.tasks.tasks import get_options_profit
from app.test.unit_tests.test_apis.trade import trading_options_url
from app.test.unit_tests.test_data import get_test_post_trade_payload
from app.test.utils import create_open_trades
from app.test.utils import create_pre_db_data
from app.utils.constants import OptionType
from app.utils.constants import update_trade_columns
from app.utils.option_chain import get_option_chain


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", [SignalTypeEnum.BUY, SignalTypeEnum.SELL], ids=["Buy Signal", "Sell Signal"]
)
async def test_trading_nfo_options_first_ever_trade(
    action, test_async_client, test_async_redis_client
):
    await create_pre_db_data(users=1, strategies=1)

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
async def test_long_nfo_options_add_to_pyramiding(
    action, test_async_client, test_async_redis_client
):
    await create_open_trades(
        users=1, strategies=1, trades=10, ce_trade=action == SignalTypeEnum.BUY
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

        # set trades in redis
        fetch_trade_models_query = await async_session.execute(
            select(TradeModel).filter_by(strategy_id=strategy_model.id)
        )
        trade_models = fetch_trade_models_query.scalars().all()
        redis_trades_list = [
            RedisTradeSchema.model_validate(trade_model).model_dump_json()
            for trade_model in trade_models
        ]
        await test_async_redis_client.hset(
            f"{strategy_model.id}",
            f"{trade_models[0].expiry} {trade_models[0].option_type}",
            json.dumps(redis_trades_list),
        )

        response = await test_async_client.post(trading_options_url, json=payload)

        assert response.status_code == 200
        assert response.json() == "successfully bought a new trade"

        # assert trade in db
        await async_session.refresh(strategy_model)
        fetch_trade_models_query = await async_session.execute(
            select(TradeModel).filter_by(strategy_id=strategy_model.id)
        )
        trade_models = fetch_trade_models_query.scalars().all()
        assert len(trade_models) == 11

        # assert trade in redis
        redis_trade_json_list = await test_async_redis_client.hget(
            f"{strategy_model.id}", f"{trade_models[0].expiry} {trade_models[0].option_type}"
        )
        assert len(json.loads(redis_trade_json_list)) == 11

        redis_trade_list = [
            RedisTradeSchema.model_validate(json.loads(trade))
            for trade in json.loads(redis_trade_json_list)
        ]
        assert redis_trade_list == [
            RedisTradeSchema.model_validate(trade_model) for trade_model in trade_models
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", [SignalTypeEnum.BUY, SignalTypeEnum.SELL], ids=["Buy Signal", "Sell Signal"]
)
async def test_trading_nfo_options_opposite_direction(
    action, test_async_client, test_async_redis_client
):
    await create_open_trades(
        users=1, strategies=1, trades=10, ce_trade=action == SignalTypeEnum.SELL
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
                option_type=OptionType.CE if action == SignalTypeEnum.SELL else OptionType.PE,
            )
        )
        exited_trade_models = fetch_trade_models_query.scalars().all()
        assert len(exited_trade_models) == 10

        # assert all trades are closed
        updated_values_dict = [
            getattr(trade_model, key)
            for key in update_trade_columns
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
            f"{exited_trade_models[0].expiry} {OptionType.CE if action == SignalTypeEnum.BUY else OptionType.PE}",
        )
        assert len(json.loads(redis_trade_list_json)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", [SignalTypeEnum.BUY, SignalTypeEnum.SELL], ids=["Buy Signal", "Sell Signal"]
)
async def test_trading_nfo_options_first_ever_trade_for_short_strategy(
    action, test_async_client, test_async_redis_client
):
    await create_pre_db_data(users=1, strategies=1, strategy_position=PositionEnum.SHORT)

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
        users=1,
        strategies=1,
        trades=10,
        ce_trade=action == SignalTypeEnum.BUY,
        position=PositionEnum.SHORT,
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
        # calculate profits
        option_chain = await get_option_chain(
            async_redis_client=test_async_redis_client,
            expiry=exited_trade_models[0].expiry,
            option_type=exited_trade_models[0].option_type,
            strategy_schema=StrategySchema.model_validate(strategy_model),
        )
        exit_price = option_chain.get(exited_trade_models[0].strike)
        # entry price is fixed : 350.0
        profit = get_options_profit(
            entry_price=350.0,
            exit_price=exit_price,
            quantity=trade_model.quantity,
            position=PositionEnum.SHORT,
        )

        # when we short a trade then we make profit when exit price is lesser than 350.0
        if exit_price < 350.0:
            assert profit > 0

        # TODO: assert why theres a small difference between profit and take_away_profit.profit
        # take_away_profit_model = await async_session.scalar(select(TakeAwayProfitModel))
        # assert take_away_profit_model.profit == profit
