import asyncio
import logging

import httpx

from app.api.trade.capital.utils import find_position
from app.api.trade.capital.utils import get_lots_to_trade_and_profit_or_loss
from app.api.trade.capital.utils import open_order_found
from app.api.trade.capital.utils import update_cfd_strategy_funds
from app.broker_clients.async_capital import AsyncCapitalClient
from app.pydantic_models.strategy import CFDStrategyPydModel
from app.pydantic_models.trade import CFDPayloadPydModel


async def close_capital_lots(
    *,
    client: AsyncCapitalClient,
    lots_to_close: float,
    cfd_strategy_pyd_model: CFDStrategyPydModel,
    cfd_payload_pyd_model: CFDPayloadPydModel,
    demo_or_live: str,
    profit_or_loss: float,
    crucial_details: str,
):
    close_lots_attempt = 1
    while close_lots_attempt <= 10:
        try:
            response = await client.create_position(
                epic=cfd_strategy_pyd_model.instrument,
                direction=cfd_payload_pyd_model.direction,
                size=lots_to_close,
            )

            response_json = response.json()
            if response_json["dealStatus"] == "ACCEPTED":
                msg = f"[ {crucial_details} ] - successfully closed [  {lots_to_close} ] trades."
                logging.info(msg)
                return False
            elif response_json["dealStatus"] == "REJECTED":
                if response_json["rejectReason"] == "THROTTLING":
                    msg = f"[ {crucial_details} ] - Attempt [ {close_lots_attempt} ] throttled while closing open lots [ {lots_to_close} ] response:  {response_json}"
                    logging.warning(msg)
                    close_lots_attempt += 1
                    await asyncio.sleep(2)
                    continue
                logging.warning(
                    f"[ {crucial_details} ] - Attempt [ {close_lots_attempt} ], rejected closing open lots [ {lots_to_close} ] response:  {response_json}. Attempting again to close"
                )
            else:
                msg = f"[ {crucial_details} ] - Attempt [ {close_lots_attempt} ] deal status: {response_json}"
                logging.error(msg)
        except httpx.HTTPStatusError as error:
            response_json = error.response
            status_code, text = response_json.status_code, response_json.text
            if status_code in [400, 404, 429]:
                logging.warning(
                    f"[ {crucial_details} ] - Attempt [ {close_lots_attempt} ] while closing lots {status_code} {text}"
                )
                await asyncio.sleep(3)
                logging.info(
                    f"[ {crucial_details} ] - may be lots are closed , so fetching all positions again and verifying the same"
                )

                _open_order_found = await open_order_found(
                    client=client,
                    cfd_strategy_pyd_model=cfd_strategy_pyd_model,
                    cfd_payload_pyd_model=cfd_payload_pyd_model,
                    lots_size=lots_to_close,
                    crucial_details=crucial_details,
                )

                if _open_order_found:
                    break

                await asyncio.sleep(1)
                position_found = await find_position(
                    client=client,
                    demo_or_live=demo_or_live,
                    cfd_strategy_pyd_model=cfd_strategy_pyd_model,
                    current_open_lots=lots_to_close,
                    action="closed",
                    crucial_details=crucial_details,
                )

                if position_found:
                    if (
                        position_found["position"]["direction"]
                        == cfd_payload_pyd_model.direction.upper()
                    ):
                        logging.warning(
                            f"[ {crucial_details} ] - Lots [ {lots_to_close} ] are reversed in [ {cfd_payload_pyd_model.direction} ] direction. so NO need to open lots again"
                        )
                        await update_cfd_strategy_funds(
                            cfd_strategy_pyd_model=cfd_strategy_pyd_model,
                            crucial_details=crucial_details,
                            profit_or_loss=profit_or_loss,
                        )
                        # TODO: try to open lots with the profit gained
                        break
                    else:
                        logging.warning(
                            f"[ {crucial_details} ] - Lots [ {lots_to_close} ] are not closed. Hence trying again to close them"
                        )
                        close_lots_attempt += 1
                        await asyncio.sleep(3)
                else:
                    logging.warning(
                        f"[ {crucial_details} ] - Lots [ {lots_to_close} ] are closed as no position found."
                    )
                    break
            else:
                msg = f"[ {crucial_details} ] - Attempt [ {close_lots_attempt} ] Error occured while closing open lots, Error: {text}"
                logging.error(msg)
                return False


async def open_capital_lots(
    *,
    client: AsyncCapitalClient,
    cfd_strategy_pyd_model: CFDStrategyPydModel,
    cfd_payload_pyd_model: CFDPayloadPydModel,
    demo_or_live: str,
    profit_or_loss: float,
    funds_to_use=float,
    crucial_details: str,
):
    lots_to_open, update_profit_or_loss_in_db = get_lots_to_trade_and_profit_or_loss(
        funds_to_use, cfd_strategy_pyd_model, profit_or_loss, crucial_details
    )

    place_order_attempt = 1
    while place_order_attempt < 10:
        try:
            response = await client.create_position(
                epic=cfd_strategy_pyd_model.instrument,
                direction=cfd_payload_pyd_model.direction,
                size=lots_to_open,
            )

            response_json = response.json()
            if response_json["dealStatus"] == "REJECTED":
                if response_json["rejectReason"] == "THROTTLING":
                    # handled rejectReason: 'THROTTLING' i.e. try again
                    msg = f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] throttled while opening lots [ {lots_to_open} ] response:  {response_json}"
                    logging.warning(msg)
                    logging.info(
                        f"[ {demo_or_live} {cfd_strategy_pyd_model.instrument} ] attempting again to open lots"
                    )
                    place_order_attempt += 1
                    await client.__log_out__()
                    await asyncio.sleep(2)
                    continue
                elif response_json["rejectReason"] == "RISK_CHECK":
                    # handle rejectReason: RISK_CHECK i.e. calculate lots to open again as available funds are updated
                    # calculate lots to open again as available funds are updated
                    msg = f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] RISK_CHECK while opening lots [ {lots_to_open} ] response:  {response_json}"
                    logging.warning(msg)
                    logging.info(
                        f"[ {crucial_details} ] calculating lots to open again as available funds are updated"
                    )
                    # funds_to_use = await get_funds_to_use(client, cfd_strategy_pyd_model)

                    (
                        lots_to_open,
                        update_profit_or_loss_in_db,
                    ) = get_lots_to_trade_and_profit_or_loss(
                        0.0, cfd_strategy_pyd_model, profit_or_loss, crucial_details
                    )
                    place_order_attempt += 1
                    await client.__log_out__()
                    await asyncio.sleep(1)
                    continue
                else:
                    logging.error(
                        f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] rejected, deal status: {response_json['dealStatus']}, reason: {response_json['rejectReason']}, status: {response_json['status']}"
                    )
                    return response_json
            elif response_json["dealStatus"] == "ACCEPTED":
                long_or_short = "LONG" if cfd_payload_pyd_model.direction == "buy" else "SHORT"
                msg = f"[ {crucial_details} ] - successfully [ {long_or_short}  {lots_to_open} ] trades."
                logging.info(msg)
            else:
                msg = f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] Error in placing open lots, deal status: {response_json}"
                logging.error(msg)

            if update_profit_or_loss_in_db:
                # update funds balance
                await update_cfd_strategy_funds(
                    cfd_strategy_pyd_model=cfd_strategy_pyd_model,
                    crucial_details=crucial_details,
                    profit_or_loss=update_profit_or_loss_in_db,
                )
            else:
                logging.info(f"[ {crucial_details} ] : No profit or loss to update in db")
            return msg
        except httpx.HTTPStatusError as error:
            response_json = error.response
            status_code, text = response_json.status_code, response_json.text
            if status_code == 429:
                logging.warning(
                    f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] throttled while opening lots [ {lots_to_open} ] {status_code} {text}"
                )
                logging.info(f"[ {crucial_details} ] : attempting again to open lots")
                # too many requests
                place_order_attempt += 1
                await client.__log_out__()
                await asyncio.sleep(2)
            elif status_code in [400, 404]:
                # # if it throws 404 exception saying dealreference not found then try to fetch all positions
                # # and see if order is placed and if not then try it again and if it is placed then skip it
                logging.warning(
                    f"[ {crucial_details} ] - Attempt [ {place_order_attempt} ] while opening lots {status_code} {text}"
                )
                await asyncio.sleep(2)
                logging.info(
                    f"[ {demo_or_live} {cfd_strategy_pyd_model.instrument} ] may be lots are opened , so fetching all positions againa and verifying the same"
                )

                _open_order_found = await open_order_found(
                    client=client,
                    cfd_strategy_pyd_model=cfd_strategy_pyd_model,
                    cfd_payload_pyd_model=cfd_payload_pyd_model,
                    lots_size=lots_to_open,
                    crucial_details=crucial_details,
                )

                if _open_order_found:
                    break

                position_found = await find_position(
                    client=client,
                    demo_or_live=demo_or_live,
                    cfd_strategy_pyd_model=cfd_strategy_pyd_model,
                    current_open_lots=lots_to_open,
                    action="open",
                    crucial_details=crucial_details,
                )

                if position_found:
                    response_direction = position_found["position"]["direction"]
                    response_lots = position_found["position"]["size"]
                    if (
                        position_found["position"]["direction"]
                        == cfd_payload_pyd_model.direction.upper()
                    ):
                        long_or_short = (
                            "LONG" if cfd_payload_pyd_model.direction == "buy" else "SHORT"
                        )
                        msg = f"[ {crucial_details} ] - successfully [ {long_or_short}  {lots_to_open} ] trades."
                        logging.info(msg)

                        await update_cfd_strategy_funds(
                            cfd_strategy_pyd_model=cfd_strategy_pyd_model,
                            crucial_details=crucial_details,
                            profit_or_loss=profit_or_loss,
                        )
                        # TODO: try to open lots with the profit gained
                        break
                    else:
                        # very rare case where lots are still in current direction.
                        # trying to close them by updating "lots_to_open" to the lots from position response
                        logging.warning(
                            f"[ {crucial_details} ] - lots are still in current [ {response_direction} ] direction. trying to close [ {response_lots} ] lots."
                        )
                        lots_to_open = response_lots
                        place_order_attempt += 1
                        await asyncio.sleep(3)
                else:
                    place_order_attempt += 1
                    await asyncio.sleep(1)
            else:
                msg = f"[ {crucial_details} ] - Error occured while opening lots, Error: {text}"
                logging.error(msg)
                return msg
