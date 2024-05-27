import datetime
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from pydantic import Field

from app.pydantic_models.enums import InstrumentTypeEnum
from app.pydantic_models.enums import SignalTypeEnum


class VarietyEnum(str, Enum):
    NORMAL = "NORMAL"
    STOPLOSS = "STOPLOSS"
    ROBO = "ROBO"


class TransactionTypeEnum(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderTypeEnum(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOPLOSS_LIMIT = "STOPLOSS_LIMIT"
    STOPLOSS_MARKET = "STOPLOSS_MARKET"


class ProductTypeEnum(str, Enum):
    DELIVERY = "DELIVERY"
    CARRYFORWARD = "CARRYFORWARD"
    MARKET = "MARKET"
    INTRADAY = "INTRADAY"
    BO = "BO"


class DurationEnum(str, Enum):
    DAY = "DAY"
    IOC = "IOC"


class ExchangeEnum(str, Enum):
    BSE = "BSE"
    NSE = "NSE"
    NFO = "NFO"
    MCX = "MCX"
    BFO = "BFO"
    CDS = "CDS"


class PlaceOrderPydanticModel(BaseModel):
    class Config:
        use_enum_values = True

    variety: VarietyEnum
    transactiontype: TransactionTypeEnum
    ordertype: OrderTypeEnum
    producttype: ProductTypeEnum
    duration: DurationEnum
    exchange: ExchangeEnum


class CreateOrderPydanticModel(BaseModel):
    class Config:
        from_attributes = True

    order_id: str
    unique_order_id: uuid.UUID
    instrument: str
    quantity: int
    future_entry_price_received: float
    entry_received_at: datetime.datetime
    entry_at: datetime.datetime = datetime.datetime.utcnow()
    strike: Optional[float] = None
    option_type: Optional[str] = None
    expiry: datetime.date
    action: SignalTypeEnum
    strategy_id: uuid.UUID


class InstrumentPydanticModel(BaseModel):
    class Config:
        use_enum_values = True

    exch_seg: ExchangeEnum = Field(..., alias="exch_seg", example="NFO")
    expiry: str = Field(..., example="29MAY2024")
    instrumenttype: InstrumentTypeEnum = Field(..., example="FUTIDX")
    lotsize: int = Field(..., example=15)
    name: str = Field(..., example="BANKNIFTY")
    strike: float = Field(..., example="-1.000000")
    symbol: str = Field(..., example="BANKNIFTY29MAY24FUT")
    tick_size: float = Field(..., example="5.000000")
    token: str = Field(..., example="46923")


class OrderDataPydModel(BaseModel):
    script: str = Field(..., example="BANKNIFTY29MAY24FUT")
    orderid: str = Field(..., example="200910000000111")
    uniqueorderid: uuid.UUID = Field(..., example="bcd193be-0bb6-476a-b397-a70376d166cb")


class OrderResponsePydModel(BaseModel):
    status: bool = Field(..., example=True)
    message: str = Field(..., example="SUCCESS")
    errorcode: str = Field(..., example="")
    data: OrderDataPydModel | None = Field(default=None)

    class Config:
        populate_by_name = True
