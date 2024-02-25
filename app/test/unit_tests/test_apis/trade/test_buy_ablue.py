import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.broker.AsyncPya3AliceBlue import AsyncPya3Aliceblue
from app.database.models import StrategyModel
from app.database.models import TradeModel
from app.database.models import User
from app.database.session_manager.db_session import Database
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.test.factory.broker import BrokerFactory
from app.test.unit_tests.test_apis.trade import trading_options_url
from app.test.unit_tests.test_data import get_test_post_trade_payload
from app.test.utils import create_open_trades
from app.utils.constants import FUT
from app.utils.constants import STRATEGY
from app.utils.constants import OptionType
from app.utils.constants import Status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "instrument_type,action",
    [
        (InstrumentTypeEnum.OPTIDX, SignalTypeEnum.BUY),
        (InstrumentTypeEnum.FUTIDX, SignalTypeEnum.BUY),
        (InstrumentTypeEnum.OPTIDX, SignalTypeEnum.SELL),
        (InstrumentTypeEnum.FUTIDX, SignalTypeEnum.SELL),
    ],
    ids=["Options Buy", "Futures Buy", "Options Sell", "Futures Sell"],
)
async def test_buy_alice_blue_trade(
    instrument_type, action, test_async_client, test_async_redis_client, monkeypatch
):
    await create_open_trades(
        test_async_redis_client=test_async_redis_client,
        users=1,
        strategies=1,
        instrument_type=instrument_type,
    )

    async with Database() as async_session:
        user_model = await async_session.scalar(select(User))
        broker_model = await BrokerFactory(user_id=user_model.id)
        strategy_model = await async_session.scalar(select(StrategyModel))
        strategy_model.broker_id = broker_model.id
        await async_session.flush()

        payload = get_test_post_trade_payload(action=action)
        payload["strategy_id"] = str(strategy_model.id)

        # set strategy in redis
        await test_async_redis_client.hset(
            str(strategy_model.id),
            STRATEGY,
            StrategySchema.model_validate(strategy_model).model_dump_json(),
        )

        # set trades in redis
        fetch_trade_models_query = await async_session.execute(
            select(TradeModel).filter_by(strategy_id=strategy_model.id)
        )
        trade_models = fetch_trade_models_query.scalars().all()
        for trade_model in trade_models:
            await test_async_redis_client.hset(
                f"{strategy_model.id}",
                f"{trade_model.expiry} {trade_model.option_type}",
                RedisTradeSchema.model_validate(trade_model).model_dump_json(),
            )

        await async_session.commit()

    # Mock the place_order method
    async def mock_place_order(*args, **kwargs):
        return {"stat": "ok", "NOrdNo": "1234567890"}

    async def mock_get_order_history(*args, **kwargs):
        return {"Avgprc": 410.5, "Status": Status.COMPLETE}

    # Use monkeypatch to patch the method
    monkeypatch.setattr(
        AsyncPya3Aliceblue, "place_order", AsyncMock(side_effect=mock_place_order)
    )
    monkeypatch.setattr(
        AsyncPya3Aliceblue, "get_order_history", AsyncMock(side_effect=mock_get_order_history)
    )

    response = await test_async_client.post(trading_options_url, json=payload)

    assert response.status_code == 200
    assert response.json() == "successfully bought a new trade"

    async with Database() as async_session:
        # assert trade in db
        strategy_model = await async_session.scalar(select(StrategyModel))
        fetch_trade_models_query = await async_session.execute(
            select(TradeModel).filter_by(strategy_id=strategy_model.id)
        )
        trade_models = fetch_trade_models_query.scalars().all()
        assert len(trade_models) == 1

        # assert trade in redis
        if instrument_type == InstrumentTypeEnum.OPTIDX:
            redis_hash = f"{trade_models[0].expiry} {trade_models[0].option_type}"
        else:
            redis_hash = f"{trade_models[0].expiry} {PositionEnum.LONG if payload['action'] == SignalTypeEnum.BUY else PositionEnum.SHORT} {FUT}"
        redis_trade_json = await test_async_redis_client.hget(f"{strategy_model.id}", redis_hash)
        redis_trade_json_list = json.loads(redis_trade_json)
        assert len(redis_trade_json_list) == 1

        redis_trade_list = [
            RedisTradeSchema.model_validate_json(trade) for trade in redis_trade_json_list
        ]
        assert redis_trade_list == [
            RedisTradeSchema.model_validate(trade_model) for trade_model in trade_models
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "option_type", [OptionType.CE, OptionType.PE], ids=["CE Options", "PE Options"]
)
async def test_buy_alice_blue_trade_raise_401(
    option_type, test_async_client, test_async_redis_client, monkeypatch
):
    await create_open_trades(
        test_async_redis_client=test_async_redis_client, users=1, strategies=1
    )

    async with Database() as async_session:
        user_model = await async_session.scalar(select(User))
        broker_model = await BrokerFactory(user_id=user_model.id)
        strategy_model = await async_session.scalar(select(StrategyModel))
        strategy_model.broker_id = broker_model.id
        await async_session.flush()

        payload = get_test_post_trade_payload()
        payload["strategy_id"] = str(strategy_model.id)

        if option_type == OptionType.PE:
            payload["option_type"] = OptionType.PE

        # set strategy in redis
        await test_async_redis_client.hset(
            str(strategy_model.id),
            STRATEGY,
            StrategySchema.model_validate(strategy_model).model_dump_json(),
        )

        # set trades in redis
        fetch_trade_models_query = await async_session.execute(
            select(TradeModel).filter_by(strategy_id=strategy_model.id)
        )
        trade_models = fetch_trade_models_query.scalars().all()
        for trade_model in trade_models:
            await test_async_redis_client.hset(
                str(strategy_model.id),
                f"{trade_model.expiry} {trade_model.option_type}",
                RedisTradeSchema.model_validate(trade_model).model_dump_json(),
            )

        await async_session.commit()

    # Use monkeypatch to patch the method
    monkeypatch.setattr(
        AsyncPya3Aliceblue,
        "place_order",
        AsyncMock(
            side_effect=[
                {"stat": "Not_ok", "emsg": "401 - Unauthorized", "encKey": None},  # first call
                {"stat": "ok", "NOrdNo": "1234567890"},  # second call
            ]
        ),
    )

    async def mock_get_order_history(*args, **kwargs):
        return {"Avgprc": 410.5, "Status": Status.COMPLETE}

    # Use monkeypatch to patch the method
    monkeypatch.setattr(
        AsyncPya3Aliceblue, "get_order_history", AsyncMock(side_effect=mock_get_order_history)
    )

    async def mock_update_session_token(*args, **kwargs):
        return "valid_session_token"

    # Use monkeypatch to patch the method
    monkeypatch.setattr(
        "app.broker.utils.update_session_token",
        AsyncMock(side_effect=mock_update_session_token),
    )

    response = await test_async_client.post(trading_options_url, json=payload)

    assert response.status_code == 200
    assert response.json() == "successfully bought a new trade"

    async with Database() as async_session:
        # assert trade in db
        strategy_model = await async_session.scalar(select(StrategyModel))
        fetch_trade_models_query = await async_session.execute(
            select(TradeModel).filter_by(strategy_id=strategy_model.id)
        )
        trade_models = fetch_trade_models_query.scalars().all()
        assert len(trade_models) == 1

        # assert trade in redis
        redis_trade_json = await test_async_redis_client.hget(
            f"{strategy_model.id}",
            f"{trade_models[0].expiry} {trade_models[0].option_type}",
        )

        redis_trade_json_list = json.loads(redis_trade_json)
        assert len(redis_trade_json_list) == 1

        redis_trade_list = [
            RedisTradeSchema.model_validate_json(trade) for trade in redis_trade_json_list
        ]
        assert redis_trade_list == [
            RedisTradeSchema.model_validate(trade_model) for trade_model in trade_models
        ]
