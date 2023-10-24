import uuid
from datetime import date
from datetime import datetime
from typing import Optional

from pydantic import BaseConfig
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from app.schemas.enums import DirectionEnum
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum


class SignalPayloadSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    quantity: int = Field(description="Quantity", example=25)
    future_entry_price_received: float = Field(description="Future Entry Price", example=40600.5)
    strategy_id: uuid.UUID = Field(
        description="Strategy ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3"
    )
    option_type: OptionTypeEnum = Field(
        description="Option Type",
        example="CE",
    )
    received_at: datetime = Field(description="Received At", example="2023-05-22 05:11:01.117358")
    premium: Optional[float] = Field(description="Premium", example=350.0, default=0.0)
    strike: Optional[float] = Field(description="Strike", example=42500.0, default=0.0)
    position: PositionEnum = Field(description="Position", example="LONG")
    broker_id: Optional[uuid.UUID] = Field(
        description="Broker ID", example="dd9acef9-e6c4-4792-9d43-d266b4d685c3", default=None
    )
    expiry: Optional[date] = Field(description="Expiry", example="2023-06-16", default=None)


class RedisTradeSchema(SignalPayloadSchema):
    # main purpose is for testing

    id: uuid.UUID = Field(description="Trade ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3")
    strike: float = Field(description="Strike", example=42500.0)
    entry_price: float = Field(description="Entry Price", example=350.5)
    future_entry_price: float = Field(description="Future Entry Price", example=40600.5)
    expiry: date = Field(description="Expiry", example="2023-06-16")
    instrument: str = Field(description="Instrument", example="BANKNIFTY16JUN2343500CE")
    entry_received_at: datetime = Field(
        description="Received At", example="2023-05-22 05:11:01.117358"
    )
    # the reason i am making it as optional even though its being inherited from
    # EntryTradeSchema, because when i use from_orm then TradeModel doesnt have symbol and validation fails
    symbol: Optional[str] = Field(description="Symbol", example="BANKNIFTY", default="")
    received_at: Optional[datetime] = Field(
        description="Received At", example="2023-05-22 05:11:01.117358", default=None
    )

    class Config(BaseConfig):
        exclude = {"symbol", "receive_at"}
        json_encoders = {
            datetime: lambda dt: dt.isoformat(),
            datetime.date: lambda d: d.isoformat(),
            uuid.UUID: str,
            PositionEnum: lambda p: p.value,
            OptionTypeEnum: lambda o: o.value,
        }


class ExitTradeSchema(BaseModel):
    id: uuid.UUID = Field(description="Trade ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3")
    exit_price: float = Field(description="Exit Price", example=450.5)
    profit: float = Field(description="Profit", example=2500.0)
    future_exit_price: float = Field(description="Future Exit Price", example=40700.5)
    future_profit: float = Field(description="Future Profit", example=2500.0)
    exit_at: datetime = Field(
        description="Exited At", default=datetime.utcnow(), example="2023-05-22 06:25:03.117358"
    )
    exit_received_at: datetime = Field(
        description="Received Exit At", example="2023-05-22 06:25:03.117358"
    )


class EntryTradeSchema(SignalPayloadSchema):
    model_config = ConfigDict(from_attributes=True)

    entry_price: float = Field(description="Entry Price", example=350.5)
    future_entry_price: float = Field(description="Future Entry Price", example=40600.5)

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

    @model_validator(mode="before")
    def populate_instrument(cls, values):
        # it is must to send symbol
        if isinstance(values, dict):
            return {
                **values,
                "instrument": f"{values['symbol']}{values['expiry'].strftime('%d%b%y').upper()}{values['strike']}{values['option_type']}",
            }


class DBEntryTradeSchema(BaseModel):
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
    position: PositionEnum = Field(description="Position", example="LONG")
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


class CFDPayloadSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    strategy_id: uuid.UUID = Field(description="strategy id")
    direction: DirectionEnum = Field(description="Position", example="BUY")
    instrument: str = Field(description="Instrument", example="EURUSD")


class BinanceFuturesPayloadSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    symbol: str = Field(description="Symbol", example="BTCUSDT")
    quantity: int = Field(description="Quantity", example=1)
    side: DirectionEnum = Field(description="Position", example="buy")
    type: str = Field(description="Type", example="MARKET")
    ltp: float = Field(description="LTP", example="27913")

    @model_validator(mode="after")
    def serialize_side(cls, values):
        values.side = values.side.upper()
        return values
