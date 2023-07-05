import asyncio
from datetime import datetime
from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_config
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.database.models import DailyProfitModel
from app.database.models import TakeAwayProfitModel
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.tasks.utils import get_monthly_expiry_date


# Not yet tested
async def update_daily_profit():
    config = get_config()
    Database.init(get_db_url(config))

    async_redis_client = await get_redis_client(config)
    option_chain = {}
    todays_date = datetime.now().date()

    monthly_expiry_date = await get_monthly_expiry_date(async_redis_client)

    async with Database() as async_session:
        if todays_date.weekday() < 5:
            # fetch live trades from db
            strategy_id_ongoing_profit_dict = {}
            fetch_live_trades_query = await async_session.execute(
                select(TradeModel).filter(TradeModel.exit_at == None)  # noqa
            )
            live_trades = fetch_live_trades_query.scalars().all()
            for live_trade in live_trades:
                if live_trade.strategy_id not in strategy_id_ongoing_profit_dict:
                    strategy_id_ongoing_profit_dict[live_trade.strategy_id] = {
                        "profit": 0,
                        "future_profit": 0,
                    }

                options_key = (
                    f"{live_trade.strategy.symbol} {live_trade.expiry} {live_trade.option_type}"
                )
                if options_key not in option_chain:
                    option_chain[options_key] = await async_redis_client.hgetall(options_key)

                futures_key = f"{live_trade.strategy.symbol} {monthly_expiry_date} FUT"
                if futures_key not in option_chain:
                    option_chain[futures_key] = await async_redis_client.hgetall(futures_key)

                current_option_price = option_chain[options_key][str(live_trade.strike)]
                current_future_price = option_chain[futures_key]["FUT"]
                if live_trade.position == "LONG":
                    profit = (
                        float(current_option_price) - live_trade.entry_price
                    ) * live_trade.quantity - 60
                    future_profit = (
                        float(current_future_price) - live_trade.future_entry_price
                    ) * live_trade.quantity - 320

                else:
                    profit = (
                        live_trade.entry_price - float(current_option_price)
                    ) * live_trade.quantity - 60
                    future_profit = (
                        live_trade.future_entry_price - float(current_future_price)
                    ) * live_trade.quantity - 320

                strategy_id_ongoing_profit_dict[live_trade.strategy_id]["profit"] += profit
                strategy_id_ongoing_profit_dict[live_trade.strategy_id][
                    "future_profit"
                ] += future_profit

            # fetch yesterdays daily profit from db
            fetch_yesterdays_profit_query = await async_session.execute(
                select(DailyProfitModel).filter(
                    DailyProfitModel.date == todays_date - timedelta(days=1)
                )
            )
            yesterdays_profit_models = fetch_yesterdays_profit_query.scalars().all()
            strategy_id_yesterdays_profit_dict = {
                yesterdays_profit_model.strategy_id: yesterdays_profit_model
                for yesterdays_profit_model in yesterdays_profit_models
            }

            # fetch take away profit from db
            fetch_take_away_profit_query = await async_session.execute(
                select(TakeAwayProfitModel)
            )
            take_away_profit_models = fetch_take_away_profit_query.scalars().all()

            strategy_id_take_away_profit_dict = {
                take_away_profit_model.strategy_id: take_away_profit_model
                for take_away_profit_model in take_away_profit_models
            }

            daily_profit_models = []
            for strategy_id, ongoing_profit in strategy_id_ongoing_profit_dict.items():
                daily_profit_models.append(
                    DailyProfitModel(
                        **{
                            "profit": ongoing_profit["profit"]
                            + strategy_id_take_away_profit_dict[strategy_id].profit
                            or 0.0 - strategy_id_yesterdays_profit_dict[strategy_id].profit,
                            "future_profit": ongoing_profit["future_profit"]
                            + strategy_id_take_away_profit_dict[strategy_id].future_profit
                            or 0.0
                            - strategy_id_yesterdays_profit_dict[strategy_id].future_profit,
                            "date": todays_date,
                            "strategy_id": strategy_id,
                        }
                    )
                )

            async_session.add_all(daily_profit_models)
            await async_session.commit()


if __name__ == "__main__":
    asyncio.run(update_daily_profit())
