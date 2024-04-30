from datetime import timedelta

import httpx
from cron.update_daily_profit import get_holidays_list
from cron.update_daily_profit import get_last_working_date

from app.api.trade.IndianFNO.utils import get_current_and_next_expiry_from_alice_blue
from app.api.trade.IndianFNO.utils import get_monthly_expiry_date_from_alice_blue
from app.pydantic_models.enums import InstrumentTypeEnum
from app.pydantic_models.enums import PositionEnum
from app.pydantic_models.enums import SignalTypeEnum
from app.pydantic_models.strategy import StrategyPydanticModel
from app.test.factory.daily_profit import DailyProfitFactory
from app.test.factory.strategy import StrategyFactory
from app.test.factory.trade import CompletedTradeFactory
from app.test.factory.trade import LiveTradeFactory
from app.test.factory.user import UserFactory
from app.utils.constants import FUT
from app.utils.constants import OptionType
from app.utils.option_chain import get_option_chain


async def get_options_and_futures_expiry_from_alice_blue(symbol):
    current_futures_expiry, _, _ = await get_monthly_expiry_date_from_alice_blue(
        instrument_type=InstrumentTypeEnum.FUTIDX, symbol=symbol
    )
    current_options_expiry, _, _ = await get_current_and_next_expiry_from_alice_blue(
        symbol=symbol
    )
    return current_options_expiry, current_futures_expiry


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
    options_expiry_date = None
    futures_expiry_date = None
    for _ in range(users):
        user = await UserFactory()

        for _ in range(strategies):
            strategy = await StrategyFactory(
                user=user,
                created_at=user.created_at + timedelta(days=1),
                position=position,
                instrument_type=instrument_type,
            )

            if not futures_expiry_date or not options_expiry_date:
                (
                    options_expiry_date,
                    futures_expiry_date,
                ) = await get_options_and_futures_expiry_from_alice_blue(symbol=strategy.symbol)

            future_option_chain = await get_option_chain(
                async_redis_client=test_async_redis_client,
                expiry=futures_expiry_date,
                strategy_pyd_model=StrategyPydanticModel.model_validate(strategy),
                is_future=True,
            )
            future_entry_price_received = float(future_option_chain.get("FUT"))
            if instrument_type == InstrumentTypeEnum.OPTIDX:
                strike = float(
                    str(int(float(future_option_chain.get("FUT"))) // 100 * 100) + ".0"
                )
                option_chain = await get_option_chain(
                    async_redis_client=test_async_redis_client,
                    expiry=options_expiry_date,
                    strategy_pyd_model=StrategyPydanticModel.model_validate(strategy),
                    option_type=OptionType.CE if ce_trade else OptionType.PE,
                    is_future=False,
                )
                entry_price = float(option_chain.get(strike)) + (
                    -200 if position == PositionEnum.LONG else +200
                )
                for _ in range(trades):
                    await LiveTradeFactory(
                        strategy=strategy,
                        option_type=OptionType.CE if ce_trade else OptionType.PE,
                        expiry=options_expiry_date,
                        entry_price=entry_price,
                        action=action,
                        # let's assume future_entry_price_received is the same as strike
                        future_entry_price_received=future_entry_price_received,
                        strike=strike,
                    )
            else:
                for _ in range(trades):
                    await LiveTradeFactory(
                        strategy=strategy,
                        entry_price=future_entry_price_received,
                        expiry=futures_expiry_date,
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
    options_expiry_date = None
    futures_expiry_date = None
    for _ in range(users):
        user = await UserFactory()

        for _ in range(strategies):
            strategy = await StrategyFactory(
                user=user,
                created_at=user.created_at + timedelta(days=1),
                position=strategy_position,
                instrument_type=instrument_type,
            )
            if not futures_expiry_date or not options_expiry_date:
                (
                    options_expiry_date,
                    futures_expiry_date,
                ) = await get_options_and_futures_expiry_from_alice_blue(symbol=strategy.symbol)

            strike = None
            future_option_chain = await get_option_chain(
                async_redis_client=test_async_redis_client,
                expiry=futures_expiry_date,
                strategy_pyd_model=StrategyPydanticModel.model_validate(strategy),
                is_future=True,
            )
            if instrument_type == InstrumentTypeEnum.OPTIDX:
                strike = float(
                    str(int(float(future_option_chain.get("FUT"))) // 100 * 100) + ".0"
                )
                option_chain = await get_option_chain(
                    async_redis_client=test_async_redis_client,
                    expiry=options_expiry_date,
                    strategy_pyd_model=StrategyPydanticModel.model_validate(strategy),
                    option_type=OptionType.CE,
                    is_future=False,
                )
                entry_price = float(option_chain.get(strike))
                if strategy_position == PositionEnum.LONG:
                    exit_price = entry_price - 100
                    profit = exit_price - entry_price * 15
                else:
                    exit_price = entry_price + 100
                    profit = entry_price - exit_price * 15
            else:
                entry_price = float(future_option_chain.get(FUT))
                if strategy_position == PositionEnum.LONG:
                    exit_price = entry_price - 200
                    profit = exit_price - entry_price * 15
                else:
                    exit_price = entry_price + 200
                    profit = entry_price - exit_price * 15

            total_profit = 0
            total_future_profit = 0
            for _ in range(trades):
                trade = await CompletedTradeFactory(
                    strategy=strategy,
                    expiry=options_expiry_date,
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
