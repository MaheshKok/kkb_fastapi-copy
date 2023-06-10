from app.api.dependency import get_async_session
from app.api.utils import get_strike_and_entry_price
from app.database.models import Trade
from app.extensions.celery_tasks import celery
from app.utils.live_data import get_option_chain


@celery.task(name="tasks.buying_trade")
async def task_buying_trade(trade_payload, expiry: str):
    option_chain = await get_option_chain(
        trade_payload["symbol"], expiry=expiry, option_type=trade_payload["option_type"]
    )

    strike, entry_price = get_strike_and_entry_price(
        option_chain,
        trade_payload.get("strike"),
        trade_payload.get("premium"),
        trade_payload.get("future_received_entry_price"),
    )

    # TODO: please remove this when we focus on explicitly buying only futures because strike is NULL for futures
    if not strike:
        return None

    if broker_id := trade_payload.get("broker_id"):
        print("broker_id", broker_id)
        # TODO: fix this for alice blue
        # status, entry_price = buy_alice_blue_trades(
        #     data,
        #     expiry,
        #     NFO_TYPE.OPTION,
        # )

        # if status == STATUS.COMPLETE:
        #     data["entry_price"] = entry_price
        # else:
        #     # Order not successful so dont place it in db
        #     return None
        pass

    async with get_async_session() as session:
        # Use the AsyncSession to perform database operations
        # Example: Create a new entry in the database
        new_trade = Trade(strike=strike, entry_price=entry_price, **trade_payload)
        session.add(new_trade)
        await session.commit()
