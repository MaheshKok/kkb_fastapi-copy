from datetime import timedelta

import httpx
from cron.update_daily_profit import get_holidays_list
from cron.update_daily_profit import get_last_working_date

from app.api.trade.IndianFNO.utils import get_current_and_next_expiry_from_alice_blue
from app.api.trade.IndianFNO.utils import get_current_and_next_expiry_from_redis
from app.api.trade.IndianFNO.utils import get_monthly_expiry_date_from_alice_blue
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.enums import SignalTypeEnum
from app.schemas.strategy import StrategySchema
from app.test.factory.daily_profit import DailyProfitFactory
from app.test.factory.strategy import StrategyFactory
from app.test.factory.trade import CompletedTradeFactory
from app.test.factory.trade import LiveTradeFactory
from app.test.factory.user import UserFactory
from app.utils.constants import OptionType
from app.utils.option_chain import get_option_chain


option_entry_price = 350.0
future_entry_price = 44300.0


async def create_open_trades(
    test_async_redis_client,
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
                    current_expiry, _, _ = await get_current_and_next_expiry_from_redis(
                        async_redis_client=test_async_redis_client,
                        instrument_type=strategy.instrument_type,
                        symbol=strategy.symbol,
                    )
                else:
                    current_expiry, _, _ = await get_current_and_next_expiry_from_redis(
                        async_redis_client=test_async_redis_client,
                        instrument_type=InstrumentTypeEnum.FUTIDX,
                        symbol=strategy.symbol,
                    )

                expiry_date = current_expiry

            future_option_chain = await get_option_chain(
                async_redis_client=test_async_redis_client,
                expiry=expiry_date,
                strategy_schema=StrategySchema.model_validate(strategy),
                is_future=True,
            )
            strike = float(str(int(float(future_option_chain.get("FUT"))) // 100 * 100) + ".0")
            option_chain = await get_option_chain(
                async_redis_client=test_async_redis_client,
                expiry=expiry_date,
                strategy_schema=StrategySchema.model_validate(strategy),
                option_type=OptionType.CE if ce_trade else OptionType.PE,
                is_future=False,
            )
            entry_price = float(option_chain.get(strike)) + (
                -200 if position == PositionEnum.LONG else +200
            )
            future_entry_price_received = strike + (
                -200 if position == PositionEnum.LONG else +200
            )
            if instrument_type == InstrumentTypeEnum.OPTIDX:
                for _ in range(trades):
                    await LiveTradeFactory(
                        strategy=strategy,
                        option_type=OptionType.CE if ce_trade else OptionType.PE,
                        expiry=expiry_date,
                        entry_price=entry_price,
                        action=action,
                        # let's assume future_entry_price is the same as strike
                        future_entry_price_received=future_entry_price_received,
                        strike=strike,
                    )
            else:
                for _ in range(trades):
                    await LiveTradeFactory(
                        strategy=strategy,
                        expiry=expiry_date,
                        strike=None,
                        option_type=None,
                        future_entry_price_received=future_entry_price_received,
                        action=action,
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
                current_monthly_expiry, _, _ = await get_monthly_expiry_date_from_alice_blue(
                    instrument_type=strategy.instrument_type, symbol=strategy.symbol
                )
                expiry_date = current_monthly_expiry
                if instrument_type == InstrumentTypeEnum.OPTIDX:
                    current_expiry, _, _ = await get_current_and_next_expiry_from_alice_blue(
                        symbol=strategy.symbol
                    )
                    expiry_date = current_expiry

            total_profit = 0
            total_future_profit = 0
            future_option_chain = await get_option_chain(
                async_redis_client=test_async_redis_client,
                expiry=expiry_date,
                strategy_schema=StrategySchema.model_validate(strategy),
                is_future=True,
            )
            strike = float(str(int(float(future_option_chain.get("FUT"))) // 100 * 100) + ".0")
            option_chain = await get_option_chain(
                async_redis_client=test_async_redis_client,
                expiry=expiry_date,
                strategy_schema=StrategySchema.model_validate(strategy),
                option_type=OptionType.CE,
                is_future=False,
            )
            entry_price = float(option_chain.get(strike))
            exit_price = entry_price - 200
            profit = exit_price - entry_price * 15
            for _ in range(trades):
                trade = await CompletedTradeFactory(
                    strategy=strategy,
                    expiry=expiry_date,
                    action=action,
                    strike=strike,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    profit=profit,
                )
                total_profit += trade.profit
                total_future_profit += trade.future_profit

            if daily_profit:
                holidays_list = await get_holidays_list(
                    test_async_redis_client, "FO", httpx.AsyncClient()
                )
                last_working_date = get_last_working_date(holidays_list)
                await DailyProfitFactory(strategy=strategy, date=last_working_date)
