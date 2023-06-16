from datetime import timedelta

from app.utils.constants import OptionType
from test.factory.strategy import StrategyFactory
from test.factory.take_away_profit import TakeAwayProfitFactory
from test.factory.trade import CompletedTradeFactory
from test.factory.trade import LiveTradeFactory
from test.factory.user import UserFactory


async def create_open_trades(
    async_session,
    users=1,
    strategies=1,
    trades=0,
    take_away_profit=False,
    daily_profit=0,
    ce_trade=True,
):
    for _ in range(users):
        user = await UserFactory(async_session=async_session)

        for _ in range(strategies):
            strategy = await StrategyFactory(
                async_session=async_session,
                user=user,
                created_at=user.created_at + timedelta(days=1),
            )

            for _ in range(trades):
                if ce_trade:
                    await LiveTradeFactory(
                        async_session=async_session, strategy=strategy, option_type=OptionType.CE
                    )
                else:
                    await LiveTradeFactory(
                        async_session=async_session, strategy=strategy, option_type=OptionType.PE
                    )

            if take_away_profit:
                # Just assume there were trades in db which are closed and their profit was taken away
                await TakeAwayProfitFactory(
                    async_session=async_session,
                    strategy=strategy,
                    total_trades=trades,
                    profit=50000.0,
                    future_profit=75000.0,
                )


async def create_closed_trades(
    async_session, users=1, strategies=1, trades=0, take_away_profit=False, daily_profit=0
):
    for _ in range(users):
        user = await UserFactory(async_session=async_session)

        for _ in range(strategies):
            strategy = await StrategyFactory(
                async_session=async_session,
                user=user,
                created_at=user.created_at + timedelta(days=1),
            )

            total_profit = 0
            total_future_profit = 0
            for _ in range(trades):
                trade = await CompletedTradeFactory(
                    async_session=async_session, strategy=strategy
                )
                total_profit += trade.profit
                total_future_profit += trade.future_profit

            if take_away_profit:
                await TakeAwayProfitFactory(
                    async_session=async_session,
                    strategy=strategy,
                    total_trades=trades,
                    profit=total_profit,
                    future_profit=total_future_profit,
                )
