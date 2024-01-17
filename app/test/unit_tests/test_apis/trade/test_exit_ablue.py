import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.broker.alice_blue import Pya3Aliceblue
from app.database.models import StrategyModel
from app.database.models import TradeModel
from app.database.models import User
from app.database.session_manager.db_session import Database
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.test.factory.broker import BrokerFactory
from app.test.unit_tests.test_apis.trade import trading_options_url
from app.test.unit_tests.test_data import get_test_post_trade_payload
from app.test.utils import create_open_trades
from app.utils.constants import STRATEGY
from app.utils.constants import OptionType
from app.utils.constants import Status
from app.utils.constants import update_trade_columns


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action", [SignalTypeEnum.BUY, SignalTypeEnum.SELL], ids=["Buy Signal", "Sell Signal"]
)
async def test_exit_alice_blue_trade(
    action, test_async_client, test_async_redis_client, monkeypatch
):
    # If Buy Signal is generated and the unit test is exit then existing trade should be PE option and vice-versa.
    await create_open_trades(
        users=1, strategies=1, trades=10, ce_trade=action == SignalTypeEnum.SELL
    )

    async with Database() as async_session:
        user_model = await async_session.scalar(select(User))
        broker_model = await BrokerFactory(user_id=user_model.id)
        strategy_model = await async_session.scalar(select(StrategyModel))
        strategy_model.broker_id = broker_model.id
        await async_session.flush()

        payload = get_test_post_trade_payload(action.value)
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
        trade_model = trade_models[0]
        await test_async_redis_client.hset(
            f"{strategy_model.id}",
            f"{trade_model.expiry} {trade_model.option_type}",
            json.dumps(
                [
                    RedisTradeSchema.model_validate(trade_model).model_dump_json()
                    for trade_model in trade_models
                ]
            ),
        )

        await async_session.commit()

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

    response = await test_async_client.post(trading_options_url, json=payload)

    assert response.status_code == 200
    assert response.json() == "successfully closed existing trades and bought a new trade"

    async with Database() as async_session:
        # fetch closed trades in db
        strategy_model = await async_session.scalar(select(StrategyModel))
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
            {key: getattr(trade_model, key) for key in update_trade_columns}
            for trade_model in exited_trade_models
        ]
        # all parameters of a trade are updated
        assert all(updated_values_dict)

        # assert exiting trades are deleted from redis
        assert not await test_async_redis_client.hget(
            f"{strategy_model.id}",
            f"{exited_trade_models[0].expiry} {exited_trade_models[0].option_type}",
        )

        # assert new trade in redis
        redis_trade_json = await test_async_redis_client.hget(
            f"{strategy_model.id}",
            f"{exited_trade_models[0].expiry} {OptionType.CE if action == SignalTypeEnum.BUY else OptionType.PE}",
        )
        assert len(json.loads(redis_trade_json)) == 1


# TODO: we dont need below unit test because
#  401 is being raised by place_order and it is being handled in the test_ablue_buy unit test
# @pytest.mark.asyncio
# @pytest.mark.parametrize(
#     "option_type", [OptionType.CE, OptionType.PE], ids=["CE Options", "PE Options"]
# )
# async def test_exit_alice_blue_trade_raise_401(
#     option_type, test_async_client, test_async_redis_client, monkeypatch
# ):
#     await create_open_trades(
#         users=1, strategies=1, trades=10, ce_trade=option_type != OptionType.CE
#     )
#
#     async with Database() as async_session:
#         user_model = await async_session.scalar(select(User))
#         broker_model = await BrokerFactory(user_id=user_model.id)
#         strategy_model = await async_session.scalar(select(StrategyModel))
#         strategy_model.broker_id = broker_model.id
#         await async_session.flush()
#
#         payload = get_test_post_trade_payload()
#         payload["strategy_id"] = str(strategy_model.id)
#
#         if option_type == OptionType.PE:
#             payload["option_type"] = OptionType.PE
#
#         # set strategy in redis
#         await test_async_redis_client.set(
#             str(strategy_model.id), StrategySchema.model_validate(strategy_model).json()
#         )
#
#         # set trades in redis
#         fetch_trade_models_query = await async_session.execute(
#             select(TradeModel).filter_by(strategy_id=strategy_model.id)
#         )
#         trade_models = fetch_trade_models_query.scalars().all()
#         for trade_model in trade_models:
#             await test_async_redis_client.rpush(
#                 f"{strategy_model.id} {trade_model.expiry} {trade_model.option_type}",
#                 RedisTradeSchema.model_validate(trade_model).json(),
#             )
#
#         await async_session.commit()
#
#     # Use monkeypatch to patch the method
#     monkeypatch.setattr(
#         Pya3Aliceblue,
#         "place_order",
#         AsyncMock(
#             side_effect=[
#                 {"stat": "Not_ok", "emsg": "401 - Unauthorized", "encKey": None},  # first call
#                 {"stat": "ok", "NOrdNo": "1234567890"},  # second call
#             ]
#         ),
#     )
#
#     async def mock_get_order_history(*args, **kwargs):
#         return {"Avgprc": 410.5, "Status": Status.COMPLETE}
#
#     # Use monkeypatch to patch the method
#     monkeypatch.setattr(
#         Pya3Aliceblue, "get_order_history", AsyncMock(side_effect=mock_get_order_history)
#     )
#
#     async def mock_update_session_token(*args, **kwargs):
#         return "xyz"
#
#     # Use monkeypatch to patch the method
#     monkeypatch.setattr(
#         "app.services.broker.utils.update_session_token",
#         AsyncMock(side_effect=mock_update_session_token),
#     )
#     response = await test_async_client.post("/api/trades/nfo/options", json=payload)
#
#     assert response.status_code == 200
#     assert response.json() == "successfully added trade to db"
#
#     async with Database() as async_session:
#         # fetch closed trades in db
#         strategy_model = await async_session.scalar(select(StrategyModel))
#         fetch_trade_models_query = await async_session.execute(
#             select(TradeModel).filter_by(
#                 strategy_id=strategy_model.id,
#                 option_type=OptionType.CE if option_type == OptionType.PE else OptionType.PE,
#             )
#         )
#         exited_trade_models = fetch_trade_models_query.scalars().all()
#         assert len(exited_trade_models) == 10
#
#         # assert all trades are closed
#         updated_values_dict = [
#             {key: getattr(trade_model, key) for key in update_trade_mappings}
#             for trade_model in exited_trade_models
#         ]
#         # all parameters of a trade are updated
#         assert all(updated_values_dict)
#
#         # assert exiting trades are deleted from redis
#         assert not await test_async_redis_client.lrange(
#             f"{strategy_model.id} {exited_trade_models[0].expiry} {exited_trade_models[0].option_type}",
#             0,
#             -1,
#         )
#
#         # assert new trade in redis
#         redis_trade_list_json = await test_async_redis_client.lrange(
#             f"{strategy_model.id} {exited_trade_models[0].expiry} {option_type}", 0, -1
#         )
#         assert len(redis_trade_list_json) == 1
