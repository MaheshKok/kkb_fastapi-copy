from datetime import timedelta

import httpx
from cron.update_daily_profit import get_holidays_list
from cron.update_daily_profit import get_last_working_date

from app.api.trade.IndianFNO.utils import get_current_and_next_expiry_from_alice_blue
from app.api.trade.IndianFNO.utils import get_monthly_expiry_date_from_alice_blue
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.enums import SignalTypeEnum
from app.test.factory.daily_profit import DailyProfitFactory
from app.test.factory.strategy import StrategyFactory
from app.test.factory.take_away_profit import TakeAwayProfitFactory
from app.test.factory.trade import CompletedTradeFactory
from app.test.factory.trade import LiveTradeFactory
from app.test.factory.user import UserFactory
from app.utils.constants import OptionType


option_entry_price = 350.0
future_entry_price = 44300.0


async def create_open_trades(
    users=1,
    strategies=1,
    trades=0,
    action=SignalTypeEnum.BUY,
    take_away_profit=False,
    daily_profit=0,
    ce_trade=True,
    position=PositionEnum.LONG,
    instrument_type=InstrumentTypeEnum.OPTIDX,
):
    expiry_date = None
    for _ in range(users):
        user = await UserFactory()

        for _ in range(strategies):
            strategy = await StrategyFactory(
                user=user,
                created_at=user.created_at + timedelta(days=1),
                position=position,
                instrument_type=instrument_type,
            )

            if not expiry_date:
                if instrument_type == InstrumentTypeEnum.OPTIDX:
                    current_expiry, _, _ = await get_current_and_next_expiry_from_alice_blue(
                        symbol=strategy.symbol
                    )
                else:
                    current_expiry, _, _ = await get_monthly_expiry_date_from_alice_blue(
                        instrument_type=strategy.instrument_type, symbol=strategy.symbol
                    )

                expiry_date = current_expiry

            if instrument_type == InstrumentTypeEnum.OPTIDX:
                for _ in range(trades):
                    await LiveTradeFactory(
                        strategy=strategy,
                        option_type=OptionType.CE if ce_trade else OptionType.PE,
                        expiry=expiry_date,
                        entry_price=option_entry_price,
                        action=action,
                        future_entry_price_received=future_entry_price,
                    )
            else:
                for _ in range(trades):
                    await LiveTradeFactory(
                        strategy=strategy,
                        expiry=expiry_date,
                        strike=None,
                        option_type=None,
                        future_entry_price_received=future_entry_price,
                        action=action,
                    )

            if take_away_profit:
                # Just assume there were trades in db which are closed and their profit was taken away
                await TakeAwayProfitFactory(
                    strategy=strategy,
                    total_trades=trades,
                    profit=50000.0,
                    future_profit=75000.0,
                )


async def create_close_trades(
    users=1,
    strategies=1,
    trades=0,
    daily_profit=True,
    strategy_position=PositionEnum.LONG,
    instrument_type=InstrumentTypeEnum.OPTIDX,
    action=SignalTypeEnum.BUY,
    test_async_redis_client=None,
):
    expiry_date = None
    for _ in range(users):
        user = await UserFactory()

        for _ in range(strategies):
            strategy = await StrategyFactory(
                user=user,
                created_at=user.created_at + timedelta(days=1),
                position=strategy_position,
                instrument_type=instrument_type,
            )

            if not expiry_date:
                if instrument_type == InstrumentTypeEnum.OPTIDX:
                    current_expiry, _, _ = await get_current_and_next_expiry_from_alice_blue(
                        symbol=strategy.symbol
                    )
                else:
                    current_expiry, _, _ = await get_monthly_expiry_date_from_alice_blue(
                        instrument_type=strategy.instrument_type, symbol=strategy.symbol
                    )

                expiry_date = current_expiry

            total_profit = 0
            total_future_profit = 0
            for _ in range(trades):
                trade = await CompletedTradeFactory(
                    strategy=strategy, expiry=expiry_date, action=action
                )
                total_profit += trade.profit
                total_future_profit += trade.future_profit

            if daily_profit:
                holidays_list = await get_holidays_list(
                    test_async_redis_client, "FO", httpx.AsyncClient()
                )
                last_working_date = get_last_working_date(holidays_list)
                await DailyProfitFactory(strategy=strategy, date=last_working_date)
