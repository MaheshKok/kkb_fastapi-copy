import pytest
from cron.update_daily_profit import update_daily_profit
from sqlalchemy import select

from app.database.schemas import DailyProfitDBModel
from app.database.schemas import StrategyDBModel
from app.database.schemas import TradeDBModel
from app.database.session_manager.db_session import Database
from app.test.factory.trade import LiveTradeFactory
from app.test.utils import create_close_trades
from app.test.utils import create_open_trades


@pytest.mark.asyncio
async def test_upate_daily_profit_or_loss_in_db_for_first_time(
    test_config, test_async_redis_client
):
    await create_open_trades(test_async_redis_client=test_async_redis_client, trades=1)
    await update_daily_profit(test_config)
    async with Database() as async_session:
        daily_profit_query = await async_session.execute(select(DailyProfitDBModel))
        daily_profit_model = daily_profit_query.scalars().all()
        assert len(daily_profit_model) == 1


@pytest.mark.asyncio
async def test_upate_daily_profit_or_loss_in_db_for_second_time(
    test_config, test_async_redis_client
):
    await create_close_trades(trades=1, test_async_redis_client=test_async_redis_client)
    async with Database() as async_session:
        strategy_query = await async_session.execute(select(StrategyDBModel))
        strategy_db_model = strategy_query.scalars().first()
        await LiveTradeFactory()

        live_trade_query = await async_session.execute(
            select(TradeDBModel).filter(TradeDBModel.exit_at == None)  # noqa
        )
        live_trade_db_models = live_trade_query.scalars().all()
        live_trade_db_model = live_trade_db_models[0]
        live_trade_db_model.strategy = strategy_db_model
        live_trade_db_model.strategy_id = strategy_db_model.id
        # await async_session.add(trade_db_model)
        await async_session.flush()
        await async_session.commit()

        await async_session.refresh(live_trade_db_model)
        await update_daily_profit(test_config)

        daily_profit_query = await async_session.execute(select(DailyProfitDBModel))
        daily_profit_model = daily_profit_query.scalars().all()
        assert len(daily_profit_model) == 2


# TODO: test for only_on_expiry dailyprofit
