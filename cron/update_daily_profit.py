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
from app.database.models import StrategyModel
from app.database.models import TradeModel
from app.database.session_manager.db_session import Database
from app.schemas.enums import InstrumentTypeEnum
from app.tasks.tasks import get_futures_profit
from app.tasks.tasks import get_options_profit
from app.tasks.utils import get_monthly_expiry_date_from_redis


async def update_daily_profit():
    config = get_config()
    Database.init(get_db_url(config))

    async_redis_client = await get_redis_client(config)
    option_chain = {}
    todays_date = datetime.now().date()

    async with Database() as async_session:
        if todays_date.weekday() < 5:
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

                only_futures = live_trade_db.strategy.instrument_type == InstrumentTypeEnum.FUTIDX

                (
                    current_month_expiry,
                    next_month_expiry,
                    is_today_months_expiry,
                ) = await get_monthly_expiry_date_from_redis(
                    async_redis_client=async_redis_client,
                    instrument_type=InstrumentTypeEnum.FUTIDX,
                    symbol=live_trade_db.strategy.symbol,
                )

                futures_key = f"{live_trade_db.strategy.symbol} {current_month_expiry} FUT"
                if futures_key not in option_chain:
                    option_chain[futures_key] = await async_redis_client.hgetall(futures_key)

                current_future_price = option_chain[futures_key]["FUT"]
                profit = get_options_profit(
                    entry_price=live_trade_db.entry_price,
                    exit_price=float(current_future_price),
                    quantity=live_trade_db.quantity,
                    position=live_trade_db.strategy.position,
                )
                future_profit = get_futures_profit(
                    entry_price=live_trade_db.future_entry_price_received,
                    exit_price=float(current_future_price),
                    quantity=live_trade_db.quantity,
                    signal=live_trade_db.action,
                )

                if not only_futures:
                    options_key = f"{live_trade_db.strategy.symbol} {live_trade_db.expiry} {live_trade_db.option_type}"
                    if options_key not in option_chain:
                        option_chain[options_key] = await async_redis_client.hgetall(options_key)
                    current_option_price = option_chain[options_key][str(live_trade_db.strike)]

                    profit = get_options_profit(
                        entry_price=live_trade_db.entry_price,
                        exit_price=float(current_option_price),
                        quantity=live_trade_db.quantity,
                        position=live_trade_db.strategy.position,
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
            strategy_id_yesterdays_profit_model_dict = {
                yesterdays_profit_model.strategy_id: yesterdays_profit_model
                for yesterdays_profit_model in yesterdays_profit_models
            }

            strategy_query = await async_session.execute(select(StrategyModel))
            strategy_models = strategy_query.scalars().all()
            strategy_id_funds_dict = {
                strategy_model.id: {
                    "funds": strategy_model.funds,
                    "future_funds": strategy_model.future_funds,
                }
                for strategy_model in strategy_models
            }

            daily_profit_models = []
            for strategy_id, ongoing_profit in strategy_id_ongoing_profit_dict.items():
                till_yesterdays_profit_model = strategy_id_yesterdays_profit_model_dict.get(
                    strategy_id
                )
                if till_yesterdays_profit_model:
                    total_profit = round(
                        ongoing_profit["profit"]
                        + strategy_id_funds_dict.get(strategy_id)["funds"],
                        2,
                    )
                    todays_profit = round(
                        total_profit - till_yesterdays_profit_model.total_profit,
                        2,
                    )
                    total_future_profit = round(
                        ongoing_profit["future_profit"]
                        + strategy_id_funds_dict.get(strategy_id)["future_funds"],
                        2,
                    )
                    todays_future_profit = round(
                        total_future_profit - till_yesterdays_profit_model.total_future_profit,
                        2,
                    )
                else:
                    trade_query = await async_session.execute(
                        select(TradeModel).filter_by(
                            strategy_id=strategy_id,
                        )
                    )
                    trade_models = trade_query.scalars().all()
                    closed_profit = sum(
                        trade_model.profit for trade_model in trade_models if trade_model.profit
                    )
                    closed_future_profit = sum(
                        trade_model.future_profit
                        for trade_model in trade_models
                        if trade_model.future_profit
                    )

                    todays_profit = round(closed_profit + ongoing_profit["profit"], 2)
                    todays_future_profit = round(
                        closed_future_profit + ongoing_profit["future_profit"], 2
                    )

                    total_profit = round(
                        strategy_id_funds_dict.get(strategy_id)["funds"] + todays_profit, 2
                    )
                    total_future_profit = round(
                        strategy_id_funds_dict.get(strategy_id)["future_funds"]
                        + todays_future_profit,
                        2,
                    )

                daily_profit_models.append(
                    DailyProfitModel(
                        **{
                            "todays_profit": todays_profit,
                            "todays_future_profit": todays_future_profit,
                            "total_profit": total_profit,
                            "total_future_profit": total_future_profit,
                            "date": todays_date,
                            "strategy_id": strategy_id,
                        }
                    )
                )

            async_session.add_all(daily_profit_models)
            await async_session.commit()
            logging.info("Daily profit captured")
        else:
            logging.info("Cant capture daily profit on weekends")


if __name__ == "__main__":
    asyncio.run(update_daily_profit())
