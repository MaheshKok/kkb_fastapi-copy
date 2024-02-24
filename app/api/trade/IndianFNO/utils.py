from datetime import date

from app.schemas.enums import OptionTypeEnum
from app.utils.constants import ALICE_BLUE_DATE_FORMAT
from app.utils.constants import OptionType


def generate_trading_symbol(
    symbol: str,
    expiry: date,
    strike: int = None,
    option_type: OptionTypeEnum = None,
    is_fut: bool = False,
):
    if is_fut and option_type:
        raise ValueError("Either Future or Option Type is Expected and not Both")

    expiry_formatted = expiry.strftime(ALICE_BLUE_DATE_FORMAT).upper()
    if is_fut:
        return f"{symbol}{expiry_formatted}F"
    else:
        is_ce = option_type == OptionType.CE
        option_char = OptionType.CE[0] if is_ce else OptionType.PE[0]
        return f"{symbol}{expiry_formatted}{option_char}{int(strike)}"
