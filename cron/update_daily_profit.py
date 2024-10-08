import asyncio
import datetime
import json
import logging
from typing import List

import aioredis
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.trade.indian_fno.utils import get_current_and_next_expiry_from_redis
from app.api.trade.indian_fno.utils import get_futures_profit
from app.api.trade.indian_fno.utils import get_options_profit
from app.core.config import get_config
from app.database.base import get_db_url
from app.database.base import get_redis_client
from app.database.schemas import DailyProfitDBModel
from app.database.schemas import StrategyDBModel
from app.database.schemas import TradeDBModel
from app.database.session_manager.db_session import Database
from app.pydantic_models.enums import InstrumentTypeEnum


nse_headers = {
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.79 Safari/537.36",
    "Sec-Fetch-User": "?1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
}


async def get_holidays_list(async_redis_client, market, http_client):
    trading_holidays_list_raw = await async_redis_client.get(
        "indian_stock_market_trading_holidays"
    )
    if not trading_holidays_list_raw:
        response = await http_client.get(
            "https://www.nseindia.com/api/holiday-master?type=trading", headers=nse_headers
        )
        await async_redis_client.set("indian_stock_market_trading_holidays", response.text)
        trading_holidays_list_raw = response.text

    clearing_holidays_list_raw = await async_redis_client.get(
        "indian_stock_market_clearing_holidays"
    )
    if not clearing_holidays_list_raw:
        response = await http_client.get(
            "https://www.nseindia.com/api/holiday-master?type=clearing", headers=nse_headers
        )
        await async_redis_client.set("indian_stock_market_clearing_holidays", response.text)
        clearing_holidays_list_raw = response.text

    holidays_list_dt_str = [
        holiday["tradingDate"]
        for holiday in json.loads(trading_holidays_list_raw).get(market, [])
    ]
    # TODO: rethink if we have to include clearing holidays
    # holidays_list_dt_str.extend(
    #     [
    #         holiday["tradingDate"]
    #         for holiday in json.loads(clearing_holidays_list_raw).get(market, [])
    #     ]
    # )
    # remove duplicates
    holidays_list_dt_str = set(holidays_list_dt_str)
    holidays_list_dt_obj = [
        datetime.datetime.strptime(holiday, "%d-%b-%Y").date() for holiday in holidays_list_dt_str
    ]
    return holidays_list_dt_obj


def get_last_working_date(holidays_list_dt_obj):
    # Get today's date
    current_day = datetime.date.today()

    # Find out what day of the week it is
    current_day_of_week = current_day.weekday()

    if current_day_of_week in [1, 2, 3, 4, 5]:  # Tuesday, Wednesday, Thursday, Friday, Saturday
        wanted_day = current_day - datetime.timedelta(days=1)
    elif current_day_of_week == 6:  # Sunday
        wanted_day = current_day - datetime.timedelta(days=2)
    else:
        # Monday
        wanted_day = current_day - datetime.timedelta(days=3)

    # Keep checking the previous day until it's not a weekend or a holiday
    while wanted_day.weekday() >= 5 or wanted_day in holidays_list_dt_obj:
        wanted_day = wanted_day - datetime.timedelta(days=1)

    return wanted_day


async def get_strategy_id_ongoing_profit_dict(
    *, async_session: AsyncSession, async_redis_client: aioredis.Redis, todays_date: datetime.date
):
    option_chain = {}
    strategy_id_ongoing_profit_dict = {}
    # fetch live trades from db
    fetch_live_trades_query = await async_session.execute(
        select(TradeDBModel)
        .options(selectinload(TradeDBModel.strategy))
        .filter(TradeDBModel.exit_at == None, TradeDBModel.expiry >= todays_date)  # noqa
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
        ) = await get_current_and_next_expiry_from_redis(
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

    return strategy_id_ongoing_profit_dict


async def get_strategy_id_yesterdays_profit_model_dict(
    async_session: AsyncSession, holidays_list: list
):
    # fetch last working day profit from db
    fetch_yesterdays_profit_query = await async_session.execute(
        select(DailyProfitDBModel).filter(
            DailyProfitDBModel.date == get_last_working_date(holidays_list)
        )
    )
    yesterdays_profit_models = fetch_yesterdays_profit_query.scalars().all()
    return {
        yesterdays_profit_model.strategy_id: yesterdays_profit_model
        for yesterdays_profit_model in yesterdays_profit_models
    }


async def get_updated_values_for_only_expiry_strategy(
    *, async_session, strategy_db_model, todays_date
):
    todays_trade_query = await async_session.execute(
        select(TradeDBModel).filter(
            TradeDBModel.strategy_id == strategy_db_model.id,
            TradeDBModel.entry_at >= todays_date,
        )
    )
    todays_trade_db_models = todays_trade_query.scalars().all()
    todays_profit = round(sum(trade.profit for trade in todays_trade_db_models), 2)
    todays_future_profit = round(sum(trade.future_profit for trade in todays_trade_db_models), 2)
    total_profit = round(strategy_db_model.funds, 2)
    total_future_profit = round(strategy_db_model.future_funds, 2)
    return todays_profit, total_profit, todays_future_profit, total_future_profit


async def get_updated_daily_profit_values_for_first_time(
    *,
    ongoing_profit: dict,
    strategy_db_model: StrategyDBModel,
    trade_db_models: List[TradeDBModel],
):
    closed_profit = sum(
        trade_db_model.profit for trade_db_model in trade_db_models if trade_db_model.profit
    )
    closed_future_profit = sum(
        trade_db_model.future_profit
        for trade_db_model in trade_db_models
        if trade_db_model.future_profit
    )
    todays_profit = round(closed_profit + ongoing_profit["profit"], 2)
    todays_future_profit = round(closed_future_profit + ongoing_profit["future_profit"], 2)
    total_profit = round(
        strategy_db_model.funds + ongoing_profit["profit"],
        2,
    )
    total_future_profit = round(
        strategy_db_model.future_funds + todays_future_profit,
        2,
    )
    return todays_profit, total_profit, todays_future_profit, total_future_profit


def get_updated_daily_profit_values(
    *,
    ongoing_profit: dict,
    strategy_db_model: StrategyDBModel,
    till_yesterdays_profit_model: DailyProfitDBModel,
):
    total_profit = round(
        ongoing_profit["profit"] + strategy_db_model.funds,
        2,
    )
    todays_profit = round(
        total_profit - till_yesterdays_profit_model.total_profit,
        2,
    )
    total_future_profit = round(
        ongoing_profit["future_profit"] + strategy_db_model.future_funds,
        2,
    )
    todays_future_profit = round(
        total_future_profit - till_yesterdays_profit_model.total_future_profit,
        2,
    )
    return todays_profit, total_profit, todays_future_profit, total_future_profit


async def update_daily_profit(config):
    Database.init(get_db_url(config))

    async_redis_client = await get_redis_client(config)
    todays_date = datetime.datetime.now().date()
    holidays_list = await get_holidays_list(async_redis_client, "FO", httpx.AsyncClient())

    if todays_date.weekday() < 5 and todays_date not in holidays_list:
        async with Database() as async_session:
            strategy_id_ongoing_profit_dict = await get_strategy_id_ongoing_profit_dict(
                async_session=async_session,
                async_redis_client=async_redis_client,
                todays_date=todays_date,
            )
            strategy_id_yesterdays_profit_model_dict = (
                await get_strategy_id_yesterdays_profit_model_dict(
                    async_session=async_session, holidays_list=holidays_list
                )
            )
            strategy_query = await async_session.execute(select(StrategyDBModel).filter_by())
            strategy_db_models = strategy_query.scalars().all()

            daily_profit_models = []
            # for strategy_id, ongoing_profit in strategy_id_ongoing_profit_dict.items():
            for strategy_db_model in strategy_db_models:
                if strategy_db_model.only_on_expiry:
                    # we don't have ongoing profit for only on expiry as it is exited on 9:45 am UTC,
                    # so today's profit is the sum of all profit of trade executed on expiry date
                    current_expiry, _, _ = await get_current_and_next_expiry_from_redis(
                        async_redis_client=async_redis_client,
                        instrument_type=strategy_db_model.instrument_type,
                        symbol=strategy_db_model.symbol,
                    )
                    if current_expiry == todays_date:
                        (
                            todays_profit,
                            total_profit,
                            todays_future_profit,
                            total_future_profit,
                        ) = await get_updated_values_for_only_expiry_strategy(
                            async_session=async_session,
                            strategy_db_model=strategy_db_model,
                            todays_date=todays_date,
                        )
                    else:
                        # if today is not expiry then we don't update daily profit for this strategy as we don't have any trade executed
                        continue
                else:
                    ongoing_profit = strategy_id_ongoing_profit_dict.get(strategy_db_model.id)
                    if not ongoing_profit:
                        continue
                    till_yesterdays_profit_model = strategy_id_yesterdays_profit_model_dict.get(
                        strategy_db_model.id
                    )
                    if till_yesterdays_profit_model:
                        (
                            todays_profit,
                            total_profit,
                            todays_future_profit,
                            total_future_profit,
                        ) = get_updated_daily_profit_values(
                            ongoing_profit=ongoing_profit,
                            strategy_db_model=strategy_db_model,
                            till_yesterdays_profit_model=till_yesterdays_profit_model,
                        )
                    else:
                        strategy_id = str(strategy_db_model.id)
                        trade_query = await async_session.execute(
                            select(TradeDBModel).filter_by(
                                strategy_id=strategy_id,
                            )
                        )
                        trade_db_models = trade_query.scalars().all()
                        if not trade_db_models:
                            # it means that this strategy has no trade executed till date
                            continue
                        (
                            todays_profit,
                            total_profit,
                            todays_future_profit,
                            total_future_profit,
                        ) = await get_updated_daily_profit_values_for_first_time(
                            ongoing_profit=ongoing_profit,
                            strategy_db_model=strategy_db_model,
                            trade_db_models=trade_db_models,
                        )

                daily_profit_models.append(
                    DailyProfitDBModel(
                        **{
                            "todays_profit": todays_profit,
                            "todays_future_profit": todays_future_profit,
                            "total_profit": total_profit,
                            "total_future_profit": total_future_profit,
                            "date": todays_date,
                            "strategy_id": str(strategy_db_model.id),
                        }
                    )
                )

            async_session.add_all(daily_profit_models)
            await async_session.commit()
            logging.info("Daily profit captured")
    else:
        logging.info("Cant capture daily profit on weekends")


if __name__ == "__main__":
    config = get_config()
    asyncio.run(update_daily_profit(config))
