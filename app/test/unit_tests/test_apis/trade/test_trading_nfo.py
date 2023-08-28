import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.models import StrategyModel
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.strategy import StrategySchema
from app.schemas.trade import RedisTradeSchema
from app.test.unit_tests.test_apis.trade import trading_options_url
from app.test.unit_tests.test_data import get_test_post_trade_payload
from app.test.utils import create_open_trades
from app.test.utils import create_pre_db_data
from app.utils.constants import OptionType
from app.utils.constants import update_trade_columns


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "option_type", [OptionType.CE, OptionType.PE], ids=["CE Options", "PE Options"]
)
async def test_trading_nfo_options_first_ever_trade(
    option_type, test_async_client, test_async_redis_client
):
    await create_pre_db_data(users=1, strategies=1)

    async with Database() as async_session:
        strategy_model = await async_session.scalar(select(StrategyModel))
        payload = get_test_post_trade_payload()
        payload["strategy_id"] = str(strategy_model.id)

        if option_type == OptionType.PE:
            payload["option_type"] = OptionType.PE

        # set strategy in redis
        await test_async_redis_client.set(
            str(strategy_model.id),
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
        redis_trade_list_json = await test_async_redis_client.lrange(
            f"{strategy_model.id} {trade_model.expiry} {trade_model.option_type}", 0, -1
        )
        redis_trade_list = [RedisTradeSchema.parse_raw(trade) for trade in redis_trade_list_json]
        assert redis_trade_list == [RedisTradeSchema.model_validate(trade_model)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "option_type", [OptionType.CE, OptionType.PE], ids=["CE Options", "PE Options"]
)
async def test_trading_nfo_options_buy_only(
    option_type, test_async_client, test_async_redis_client
):
    await create_open_trades(
        users=1, strategies=1, trades=10, ce_trade=option_type == OptionType.CE
    )

    async with Database() as async_session:
        strategy_model = await async_session.scalar(select(StrategyModel))
        payload = get_test_post_trade_payload()
        payload["strategy_id"] = str(strategy_model.id)

        if option_type == OptionType.PE:
            payload["option_type"] = OptionType.PE

        # set strategy in redis
        await test_async_redis_client.set(
            str(strategy_model.id),
            StrategySchema.model_validate(strategy_model).model_dump_json(),
        )

        # set trades in redis
        fetch_trade_models_query = await async_session.execute(
            select(TradeModel).filter_by(strategy_id=strategy_model.id)
        )
        trade_models = fetch_trade_models_query.scalars().all()
        for trade_model in trade_models:
            await test_async_redis_client.rpush(
                f"{strategy_model.id} {trade_model.expiry} {trade_model.option_type}",
                RedisTradeSchema.model_validate(trade_model).model_dump_json(),
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
        redis_trade_list_json = await test_async_redis_client.lrange(
            f"{strategy_model.id} {trade_models[0].expiry} {trade_models[0].option_type}", 0, -1
        )
        assert len(redis_trade_list_json) == 11

        redis_trade_list = [RedisTradeSchema.parse_raw(trade) for trade in redis_trade_list_json]
        assert redis_trade_list == [
            RedisTradeSchema.model_validate(trade_model) for trade_model in trade_models
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "option_type", [OptionType.CE, OptionType.PE], ids=["CE Options", "PE Options"]
)
async def test_trading_nfo_options_sell_and_buy(
    option_type, test_async_client, test_async_redis_client
):
    await create_open_trades(
        users=1, strategies=1, trades=100, ce_trade=option_type != OptionType.CE
    )

    async with Database() as async_session:
        strategy_model = await async_session.scalar(
            select(StrategyModel).options(selectinload(StrategyModel.trades))
        )
        payload = get_test_post_trade_payload()
        payload["strategy_id"] = str(strategy_model.id)

        if option_type == OptionType.PE:
            payload["option_type"] = OptionType.PE

        # set strategy in redis
        await test_async_redis_client.set(
            str(strategy_model.id),
            StrategySchema.model_validate(strategy_model).model_dump_json(),
        )

        await async_session.refresh(strategy_model)

        # set trades in redis
        for trade_model in strategy_model.trades:
            await test_async_redis_client.rpush(
                f"{strategy_model.id} {trade_model.expiry} {trade_model.option_type}",
                RedisTradeSchema.model_validate(trade_model).model_dump_json(),
            )
            async_session.expunge(trade_model)

        response = await test_async_client.post(trading_options_url, json=payload)

        assert response.status_code == 200
        assert response.json() == "successfully closed existing trades and bought a new trade"

        # fetch closed trades in db
        fetch_trade_models_query = await async_session.execute(
            select(TradeModel).filter_by(
                strategy_id=strategy_model.id,
                option_type=OptionType.CE if option_type == OptionType.PE else OptionType.PE,
            )
        )
        exited_trade_models = fetch_trade_models_query.scalars().all()
        assert len(exited_trade_models) == 100

        # assert all trades are closed
        updated_values_dict = [
            getattr(trade_model, key)
            for key in update_trade_columns
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
