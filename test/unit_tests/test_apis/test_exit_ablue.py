from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.database.models import StrategyModel
from app.database.models import TradeModel
from app.database.models import User
from app.database.sqlalchemy_client.client import Database
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.services.broker.alice_blue import Pya3Aliceblue
from app.utils.constants import OptionType
from app.utils.constants import Status
from app.utils.constants import update_trade_mappings
from test.factory.broker import BrokerFactory
from test.unit_tests.test_data import get_test_post_trade_payload
from test.utils import create_open_trades


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "option_type", [OptionType.CE, OptionType.PE], ids=["CE Options", "PE Options"]
)
async def test_exit_alice_blue_trade(
    option_type, test_async_client, test_async_redis_client, monkeypatch
):
    await create_open_trades(
        users=1, strategies=1, trades=10, ce_trade=option_type != OptionType.CE
    )

    async with Database():
        user_model = await Database.session.scalar(select(User))
        broker_model = await BrokerFactory(user_id=user_model.id)
        strategy_model = await Database.session.scalar(select(StrategyModel))
        strategy_model.broker_id = broker_model.id
        await Database.session.flush()

        payload = get_test_post_trade_payload()
        payload["strategy_id"] = str(strategy_model.id)

        if option_type == OptionType.PE:
            payload["option_type"] = OptionType.PE

        # set strategy in redis
        await test_async_redis_client.set(
            str(strategy_model.id), StrategySchema.from_orm(strategy_model).json()
        )

        # set trades in redis
        fetch_trade_models_query = await Database.session.execute(
            select(TradeModel).filter_by(strategy_id=strategy_model.id)
        )
        trade_models = fetch_trade_models_query.scalars().all()
        for trade_model in trade_models:
            await test_async_redis_client.rpush(
                f"{strategy_model.id} {trade_model.expiry} {trade_model.option_type}",
                RedisTradeSchema.from_orm(trade_model).json(),
            )

        await Database.session.commit()

    # Mock the place_order method
    async def mock_place_order(*args, **kwargs):
        return {"stat": "ok", "NOrdNo": "1234567890"}

    async def mock_get_order_history(*args, **kwargs):
        return {"Avgprc": 410.5, "Status": Status.COMPLETE}

    # Use monkeypatch to patch the method
    monkeypatch.setattr(Pya3Aliceblue, "place_order", AsyncMock(side_effect=mock_place_order))
    monkeypatch.setattr(
        Pya3Aliceblue, "get_order_history", AsyncMock(side_effect=mock_get_order_history)
    )

    response = await test_async_client.post("/api/trading/nfo/options", json=payload)

    assert response.status_code == 200
    assert response.json() == "successfully added trade to db"

    async with Database():
        # fetch closed trades in db
        strategy_model = await Database.session.scalar(select(StrategyModel))
        fetch_trade_models_query = await Database.session.execute(
            select(TradeModel).filter_by(
                strategy_id=strategy_model.id,
                option_type=OptionType.CE if option_type == OptionType.PE else OptionType.PE,
            )
        )
        exited_trade_models = fetch_trade_models_query.scalars().all()
        assert len(exited_trade_models) == 10

        # assert all trades are closed
        updated_values_dict = [
            {key: getattr(trade_model, key) for key in update_trade_mappings}
            for trade_model in exited_trade_models
        ]
        # all parameters of a trade are updated
        assert all(updated_values_dict)

        # assert exiting trades are deleted from redis
        assert not await test_async_redis_client.lrange(
            f"{strategy_model.id} {exited_trade_models[0].expiry} {exited_trade_models[0].option_type}",
            0,
            -1,
        )

        # assert new trade in redis
        redis_trade_list_json = await test_async_redis_client.lrange(
            f"{strategy_model.id} {exited_trade_models[0].expiry} {option_type}", 0, -1
        )
        assert len(redis_trade_list_json) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "option_type", [OptionType.CE, OptionType.PE], ids=["CE Options", "PE Options"]
)
async def test_exit_alice_blue_trade_raise_401(
    option_type, test_async_client, test_async_redis_client, monkeypatch
):
    await create_open_trades(
        users=1, strategies=1, trades=10, ce_trade=option_type != OptionType.CE
    )

    async with Database():
        user_model = await Database.session.scalar(select(User))
        broker_model = await BrokerFactory(user_id=user_model.id)
        strategy_model = await Database.session.scalar(select(StrategyModel))
        strategy_model.broker_id = broker_model.id
        await Database.session.flush()

        payload = get_test_post_trade_payload()
        payload["strategy_id"] = str(strategy_model.id)

        if option_type == OptionType.PE:
            payload["option_type"] = OptionType.PE

        # set strategy in redis
        await test_async_redis_client.set(
            str(strategy_model.id), StrategySchema.from_orm(strategy_model).json()
        )

        # set trades in redis
        fetch_trade_models_query = await Database.session.execute(
            select(TradeModel).filter_by(strategy_id=strategy_model.id)
        )
        trade_models = fetch_trade_models_query.scalars().all()
        for trade_model in trade_models:
            await test_async_redis_client.rpush(
                f"{strategy_model.id} {trade_model.expiry} {trade_model.option_type}",
                RedisTradeSchema.from_orm(trade_model).json(),
            )

        await Database.session.commit()

    # Mock the place_order method
    async def mock_place_order(*args, **kwargs):
        return {"stat": "Not_ok", "emsg": "401 - Unauthorized", "encKey": None}

    # Use monkeypatch to patch the method
    monkeypatch.setattr(Pya3Aliceblue, "place_order", AsyncMock(side_effect=mock_place_order))

    response = await test_async_client.post("/api/trading/nfo/options", json=payload)

    assert response.status_code == 403
    assert response.json() == {"detail": "401 - Unauthorized"}

    async with Database():
        # assert trade in db
        strategy_model = await Database.session.scalar(select(StrategyModel))
        fetch_trade_models_query = await Database.session.execute(
            select(TradeModel).filter(
                TradeModel.strategy_id == strategy_model.id, TradeModel.exit_at is None
            )
        )
        trade_models = fetch_trade_models_query.scalars().all()
        # there wont be any trades in db
        assert len(trade_models) == 0

        # assert trade in redis
        redis_keys = await test_async_redis_client.keys()
        # there wont be any trades in redis
        assert any(str(strategy_model.id) in key for key in redis_keys)
