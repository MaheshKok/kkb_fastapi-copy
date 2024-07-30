import uuid
from datetime import date
from datetime import datetime
from typing import Optional

from pydantic import BaseConfig
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from app.pydantic_models.enums import OptionTypeEnum
from app.pydantic_models.enums import PositionEnum
from app.pydantic_models.enums import SignalTypeEnum
from app.utils.constants import ALICE_BLUE_EXPIRY_DATE_FORMAT
from app.utils.constants import OptionType


class SignalPydModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    future_entry_price_received: float = Field(description="Future Entry Price", example=40600.5)
    strategy_id: uuid.UUID = Field(
        description="Strategy ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3"
    )
    received_at: datetime = Field(description="Received At", example="2023-05-22 05:11:01.117358")
    action: SignalTypeEnum = Field(description="buy or sell signal", example="buy")
    strike: Optional[float] = Field(description="Strike", example=42500.0, default=None)

    # TODO: try removing option_type and expiry as they are set on tradeschema and then accessed
    # rather have it send as arguments to the function

    # option type is decided based on strategy's position column
    # if strategy position is long and signal action is buy, then option type is CE else PE
    # if strategy position is short and signal action is buy, then option type is PE else CE
    option_type: Optional[OptionTypeEnum] = Field(
        description="Option Type",
        example="CE",
        default=None,
    )
    expiry: Optional[date] = Field(description="Expiry", example="2023-06-16", default=None)
    quantity: Optional[int] = Field(description="Quantity", example=15, default=0)


class RedisTradePydModel(SignalPydModel):
    # the main purpose is for testing

    id: uuid.UUID = Field(description="Trade ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3")
    strike: Optional[float] = Field(description="Strike", example=42500.0, default=None)
    entry_price: Optional[float] = Field(description="Entry Price", example=350.5, default=None)
    expiry: date = Field(description="Expiry", example="2023-06-16")
    instrument: str = Field(description="Instrument", example="BANKNIFTY16JUN2343500CE")
    entry_received_at: datetime = Field(
        description="Received At", example="2023-05-22 05:11:01.117358"
    )
    # the reason i am making it as optional even though its being inherited from
    # EntryTradeSchema, because when i use from_orm then TradeModel  doesn't have symbol and validation fails
    symbol: Optional[str] = Field(description="Symbol", example="BANKNIFTY", default="")
    received_at: Optional[datetime] = Field(
        description="Received At", example="2023-05-22 05:11:01.117358", default=None
    )
    action: SignalTypeEnum = Field(description="buy or sell signal", example="buy")
    quantity: int = Field(description="Quantity", example=15)

    class Config(BaseConfig):
        exclude = {"symbol", "receive_at"}
        json_encoders = {
            datetime: lambda dt: dt.isoformat(),
            datetime.date: lambda d: d.isoformat(),
            uuid.UUID: str,
            PositionEnum: lambda p: p.value,
            OptionTypeEnum: lambda o: o.value,
        }


class ExitTradePydModel(BaseModel):
    id: uuid.UUID = Field(description="Trade ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3")
    exit_price: float = Field(description="Exit Price", example=450.5)
    profit: float = Field(description="Profit", example=2500.0)
    future_exit_price_received: float = Field(description="Future Exit Price", example=40700.5)
    future_profit: float = Field(description="Future Profit", example=2500.0)
    exit_at: datetime = Field(
        description="Exited At", default=datetime.utcnow(), example="2023-05-22 06:25:03.117358"
    )
    exit_received_at: datetime = Field(
        description="Received Exit At", example="2023-05-22 06:25:03.117358"
    )


class EntryTradePydModel(SignalPydModel):
    model_config = ConfigDict(from_attributes=True)

    entry_price: Optional[float] = Field(description="Entry Price", example=350.5, default=None)
    future_entry_price: Optional[float] = Field(
        description="Future Entry Price", example=40600.5, default=None
    )
    quantity: int = Field(description="Quantity", example=15)
    entry_at: datetime = Field(
        description="Placed At",
        default_factory=datetime.utcnow,
        example="2023-05-22 05:11:04.117358+00",
    )
    entry_received_at: datetime = Field(
        description="Received At", example="2023-05-22 05:11:01.117358"
    )

    expiry: date = Field(description="Expiry", example="2023-05-22")
    instrument: str = Field(description="Instrument name", example="BANKNIFTY27APR23FUT")
    action: SignalTypeEnum = Field(description="buy or sell signal", example="buy")

    @model_validator(mode="before")
    def populate_instrument(cls, values):
        # it must send symbol
        if isinstance(values, dict):
            values["future_entry_price_received"] = round(
                values["future_entry_price_received"], 2
            )
            if values.get("instrument"):
                return values

            # generate instrument name based on symbol, expiry and option_type and strike
            if values.get("option_type"):
                instrument = generate_trading_symbol(
                    symbol=values["symbol"],
                    expiry=values["expiry"],
                    option_type=values["option_type"],
                    strike=values["strike"],
                )
                return {**values, "instrument": instrument}
            else:
                instrument = generate_trading_symbol(
                    symbol=values["symbol"], expiry=values["expiry"], is_fut=True
                )
                return {**values, "instrument": instrument}


class FuturesEntryTradePydModel(SignalPydModel):
    model_config = ConfigDict(from_attributes=True)

    entry_price: Optional[float] = Field(description="Entry Price", example=350.5, default=None)
    future_entry_price: Optional[float] = Field(
        description="Future Entry Price", example=40600.5, default=None
    )
    quantity: int = Field(description="Quantity", example=15)
    entry_at: datetime = Field(
        description="Placed At",
        default_factory=datetime.utcnow,
        example="2023-05-22 05:11:04.117358+00",
    )
    entry_received_at: datetime = Field(
        description="Received At", example="2023-05-22 05:11:01.117358"
    )

    expiry: date = Field(description="Expiry", example="2023-05-22")
    instrument: str = Field(description="Instrument name", example="BANKNIFTY27APR23FUT")
    action: SignalTypeEnum = Field(description="buy or sell signal", example="buy")

    @model_validator(mode="before")
    def populate_instrument(cls, values):
        # it must send symbol
        if isinstance(values, dict):
            values["future_entry_price_received"] = round(
                values["future_entry_price_received"], 2
            )
            if values.get("instrument"):
                return values

            # generate instrument name based on symbol, expiry and option_type and strike
            if values.get("option_type"):
                instrument = generate_trading_symbol(
                    symbol=values["symbol"],
                    expiry=values["expiry"],
                    option_type=values["option_type"],
                    strike=values["strike"],
                )
                return {**values, "instrument": instrument}
            else:
                instrument = generate_trading_symbol(
                    symbol=values["symbol"], expiry=values["expiry"], is_fut=True
                )
                return {**values, "instrument": instrument}


class OptionsEntryTradePydModel(FuturesEntryTradePydModel):
    model_config = ConfigDict(from_attributes=True)
    strike: float = Field(description="Strike", example=42500.0, default=None)

    # option type is decided based on strategy's position column
    # if strategy position is long and signal action is buy, then option type is CE else PE
    # if strategy position is short and signal action is buy, then option type is PE else CE
    option_type: OptionTypeEnum = Field(
        description="Option Type",
        example="CE",
    )


# below schema is used only for as Response Model in endpoints where trades are retrieved from DB
class DBEntryTradePydModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    quantity: int = Field(description="Quantity", example=25)
    strategy_id: uuid.UUID = Field(
        description="Strategy ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3"
    )
    option_type: OptionTypeEnum = Field(
        description="Option Type",
        example="CE",
    )
    instrument: str = Field(description="Instrument", example="BANKNIFTY16JUN2343500CE")
    action: SignalTypeEnum = Field(description="Buy or Sell Action", example="buy")
    entry_price: float = Field(description="Entry Price", example=350.5)
    future_entry_price: float = Field(description="Future Entry Price", example=40600.5)
    future_entry_price_received: float = Field(description="Future Entry Price", example=40600.5)
    entry_received_at: datetime = Field(
        description="Received At", example="2023-05-22 05:11:01.117358"
    )
    entry_at: datetime = Field(
        description="Placed At",
        default_factory=datetime.utcnow,
        example="2023-05-22 05:11:04.117358+00",
    )
    strike: float = Field(description="Strike", example=42500.0)
    expiry: date = Field(description="Expiry", example="2023-05-22")


class CFDPayloadPydModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    strategy_id: uuid.UUID = Field(description="strategy id")
    direction: SignalTypeEnum = Field(description="buy or sell signal", example="buy")
    account_id: Optional[str] = Field(description="account id", default=None)


class FuturesPayloadSchema(CFDPayloadPydModel):
    pass


class BinanceFuturesPayloadPydModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    symbol: str = Field(description="Symbol", example="BTCUSDT")
    quantity: float = Field(description="Quantity", example=1)
    side: SignalTypeEnum = Field(description="buy or sell signal", example="buy")
    type: str = Field(description="Type", example="MARKET")
    ltp: float = Field(description="LTP", example="27913")
    is_live: bool = Field(description="trades to be executed on demo account", default=False)

    @model_validator(mode="after")
    def serialize_side(cls, values):
        values.side = values.side.upper()
        return values


def generate_trading_symbol(
    symbol: str,
    expiry: date,
    strike: int = None,
    option_type: OptionTypeEnum = None,
    is_fut: bool = False,
):
    if is_fut and option_type:
        raise ValueError("Either Future or Option Type is Expected and not Both")

    expiry_formatted = expiry.strftime(ALICE_BLUE_EXPIRY_DATE_FORMAT).upper()
    if is_fut:
        return f"{symbol}{expiry_formatted}F"
    else:
        is_ce = option_type == OptionType.CE
        option_type_initial = OptionType.CE[0] if is_ce else OptionType.PE[0]
        return f"{symbol}{expiry_formatted}{option_type_initial}{int(strike)}"
