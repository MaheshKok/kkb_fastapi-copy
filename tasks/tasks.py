from app.api.utils import get_strike_and_entry_price
from app.core.config import get_config
from app.database.base import get_async_session_maker
from app.database.base import get_db_url
from app.database.models import TradeModel
from app.extensions.celery_tasks import celery
from app.schemas.trade import TradeSchema
from app.utils.option_chain import get_option_chain


# @celery.task(name="tasks.closing_trade")
# def task_closing_trade(payload_data, redis_ongoing_trades, expiry):
#     expiry_formatted = datetime.strptime(expiry, "%d %b %Y").date().strftime("%Y-%m-%d")
#     redis_ongoing_trades_key = f"{payload_data['strategy_id']}_{expiry_formatted}_{'pe' if payload_data['option_type'] == 'ce' else 'ce'}"
#     payload_data["expiry"] = expiry
#     strike_exitprice_dict = {}
#     if broker_id := payload_data.get("broker_id"):
#         if broker_id == str(BROKER.alice_blue_id):
#             # TODO: we need data back from alice blue to update the db and then pass it to close_ongoing_trades
#             status, strike_exitprice_dict = close_alice_blue_trades(
#                 expiry,
#                 NFO_TYPE.OPTION,
#                 redis_ongoing_trades,
#                 payload_data,
#             )
#
#             if status != "success":
#                 return "failure"
#
#     return close_ongoing_trades(
#         redis_ongoing_trades,
#         payload_data,
#         redis_ongoing_trades_key,
#         broker_data=strike_exitprice_dict,
#     )
#


def _get_async_session_maker(config_file):
    config = get_config(config_file)
    async_db_url = get_db_url(config)
    return get_async_session_maker(async_db_url)


@celery.task(name="tasks.buying_trade")
async def task_buying_trade(trade_payload, config_file):
    option_chain = await get_option_chain(
        trade_payload["symbol"],
        expiry=trade_payload["expiry"],
        option_type=trade_payload["option_type"],
    )

    strike, entry_price = get_strike_and_entry_price(
        option_chain,
        option_type=trade_payload["option_type"],
        strike=trade_payload.get("strike"),
        premium=trade_payload.get("premium"),
        future_price=trade_payload.get("future_received_entry_price"),
    )

    # TODO: please remove this when we focus on explicitly buying only futures because strike is Null for futures
    if not strike:
        return None

    # if we already have a strike in the payload then remove it
    # as we have successfully fetched the available strike from option_chain
    if "strike" in trade_payload:
        trade_payload.pop("strike")

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

    async_session_maker = _get_async_session_maker(config_file)

    async with async_session_maker() as session:
        # Use the AsyncSession to perform database operations
        # Example: Create a new entry in the database
        trade_schema = TradeSchema(strike=strike, entry_price=entry_price, **trade_payload)
        new_trade = TradeModel(**trade_schema.dict(exclude={"premium"}))
        session.add(new_trade)
        await session.commit()
