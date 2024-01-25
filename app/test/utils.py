from datetime import timedelta

from app.api.utils import get_current_and_next_expiry_from_alice_blue
from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import PositionEnum
from app.schemas.strategy import StrategySchema
from app.tasks.utils import get_monthly_expiry_date_from_alice_blue
from app.test.factory.strategy import StrategyFactory
from app.test.factory.take_away_profit import TakeAwayProfitFactory
from app.test.factory.trade import CompletedTradeFactory
from app.test.factory.trade import LiveTradeFactory
from app.test.factory.user import UserFactory
from app.utils.constants import OptionType


async def create_open_trades(
    users=1,
    strategies=1,
    trades=0,
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
                    )
            else:
                for _ in range(trades):
                    await LiveTradeFactory(
                        strategy=strategy,
                        expiry=expiry_date,
                        entry_price=None,
                        strike=None,
                        option_type=None,
                    )

            if take_away_profit:
                # Just assume there were trades in db which are closed and their profit was taken away
                await TakeAwayProfitFactory(
                    strategy=strategy,
                    total_trades=trades,
                    profit=50000.0,
                    future_profit=75000.0,
                )


async def create_pre_db_data(
    users=1,
    strategies=1,
    trades=0,
    take_away_profit=False,
    daily_profit=0,
    strategy_position=PositionEnum.LONG,
    instrument_type=InstrumentTypeEnum.OPTIDX,
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
                current_expiry, _, _ = await get_current_and_next_expiry_from_alice_blue(
                    StrategySchema.model_validate(strategy)
                )
                expiry_date = current_expiry

            total_profit = 0
            total_future_profit = 0
            for _ in range(trades):
                trade = await CompletedTradeFactory(strategy=strategy, expiry=expiry_date)
                total_profit += trade.profit
                total_future_profit += trade.future_profit

            if take_away_profit:
                await TakeAwayProfitFactory(
                    strategy=strategy,
                    total_trades=trades,
                    profit=total_profit,
                    future_profit=total_future_profit,
                )
