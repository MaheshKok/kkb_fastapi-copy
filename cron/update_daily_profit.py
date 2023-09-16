import asyncio
import logging
from datetime import datetime
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_config
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.database.models import DailyProfitModel
from app.database.models import TakeAwayProfitModel
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.tasks.tasks import get_futures_profit
from app.tasks.tasks import get_options_profit
from app.tasks.utils import get_monthly_expiry_date


# Not yet tested
async def update_daily_profit():
    config = get_config()
    Database.init(get_db_url(config))

    async_redis_client = await get_redis_client(config)
    option_chain = {}
    todays_date = datetime.now().date()

    async with Database() as async_session:
        if todays_date.weekday() < 7:
            # fetch live trades from db
            strategy_id_ongoing_profit_dict = {}
            fetch_live_trades_query = await async_session.execute(
                select(TradeModel)
                .options(selectinload(TradeModel.strategy))
                .filter(TradeModel.exit_at == None, TradeModel.expiry >= todays_date)  # noqa
            )
            live_trades_db = fetch_live_trades_query.scalars().all()
            for live_trade_db in live_trades_db:
                if live_trade_db.strategy_id not in strategy_id_ongoing_profit_dict:
                    strategy_id_ongoing_profit_dict[live_trade_db.strategy_id] = {
                        "profit": 0,
                        "future_profit": 0,
                    }

                options_key = f"{live_trade_db.strategy.symbol} {live_trade_db.expiry} {live_trade_db.option_type}"
                if options_key not in option_chain:
                    option_chain[options_key] = await async_redis_client.hgetall(options_key)

                monthly_expiry_date = await get_monthly_expiry_date(
                    async_redis_client,
                    live_trade_db.strategy.instrument_type,
                    live_trade_db.strategy.symbol,
                )

                futures_key = f"{live_trade_db.strategy.symbol} {monthly_expiry_date} FUT"
                if futures_key not in option_chain:
                    option_chain[futures_key] = await async_redis_client.hgetall(futures_key)

                current_option_price = option_chain[options_key][str(live_trade_db.strike)]
                current_future_price = option_chain[futures_key]["FUT"]

                profit = get_options_profit(
                    entry_price=live_trade_db.entry_price,
                    exit_price=float(current_option_price),
                    quantity=live_trade_db.quantity,
                    position=live_trade_db.position,
                )
                future_profit = get_futures_profit(
                    entry_price=live_trade_db.future_entry_price,
                    exit_price=float(current_future_price),
                    quantity=live_trade_db.quantity,
                    position=live_trade_db.position,
                )

                strategy_id_ongoing_profit_dict[live_trade_db.strategy_id]["profit"] += profit
                strategy_id_ongoing_profit_dict[live_trade_db.strategy_id][
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
                take_away_profit_model = strategy_id_take_away_profit_dict[strategy_id]
                if take_away_profit_model:
                    take_away_profit = take_away_profit_model.profit
                    take_away_future_profit = take_away_profit_model.future_profit
                else:
                    take_away_profit = 0.0
                    take_away_future_profit = 0.0

                daily_profit_models.append(
                    DailyProfitModel(
                        **{
                            "profit": ongoing_profit["profit"] + take_away_profit
                            or 0.0 - strategy_id_yesterdays_profit_dict[strategy_id].profit,
                            "future_profit": ongoing_profit["future_profit"]
                            + take_away_future_profit
                            or 0.0 - take_away_future_profit,
                            "date": todays_date,
                            "strategy_id": strategy_id,
                        }
                    )
                )

            async_session.add_all(daily_profit_models)
            await async_session.commit()
        else:
            logging.info("Cant capture daily profit on weekends")


if __name__ == "__main__":
    asyncio.run(update_daily_profit())
