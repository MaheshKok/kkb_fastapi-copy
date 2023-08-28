from datetime import timedelta

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
):
    for _ in range(users):
        user = await UserFactory()

        for _ in range(strategies):
            strategy = await StrategyFactory(
                user=user,
                created_at=user.created_at + timedelta(days=1),
            )

            for _ in range(trades):
                if ce_trade:
                    await LiveTradeFactory(strategy=strategy, option_type=OptionType.CE)
                else:
                    await LiveTradeFactory(strategy=strategy, option_type=OptionType.PE)

            if take_away_profit:
                # Just assume there were trades in db which are closed and their profit was taken away
                await TakeAwayProfitFactory(
                    strategy=strategy,
                    total_trades=trades,
                    profit=50000.0,
                    future_profit=75000.0,
                )


async def create_pre_db_data(
    users=1, strategies=1, trades=0, take_away_profit=False, daily_profit=0
):
    for _ in range(users):
        user = await UserFactory()

        for _ in range(strategies):
            strategy = await StrategyFactory(
                user=user,
                created_at=user.created_at + timedelta(days=1),
            )

            total_profit = 0
            total_future_profit = 0
            for _ in range(trades):
                trade = await CompletedTradeFactory(strategy=strategy)
                total_profit += trade.profit
                total_future_profit += trade.future_profit

            if take_away_profit:
                await TakeAwayProfitFactory(
                    strategy=strategy,
                    total_trades=trades,
                    profit=total_profit,
                    future_profit=total_future_profit,
                )
