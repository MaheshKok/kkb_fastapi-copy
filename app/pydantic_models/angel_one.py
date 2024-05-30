import datetime
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

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


class OrderPayloadPydModel(BaseModel):
    class Config:
        use_enum_values = True

    variety: VarietyEnum
    transactiontype: TransactionTypeEnum
    ordertype: OrderTypeEnum
    producttype: ProductTypeEnum
    duration: DurationEnum
    exchange: ExchangeEnum


class InitialOrderPydModel(BaseModel):
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
    entry_exit: str


class InstrumentPydModel(BaseModel):
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
    status: Optional[bool] = Field(..., example=True)
    message: str = Field(..., example="SUCCESS")
    errorcode: str = Field(..., example="AB1012")
    data: OrderDataPydModel | None = Field(default=None)

    class Config:
        populate_by_name = True


class UpdatedOrderPydModel(OrderPayloadPydModel):
    price: float = Field(..., example=0.0)
    triggerprice: float = Field(..., example=0.0)
    quantity: float = Field(..., example="15")
    disclosedquantity: str = Field(..., example="0")
    squareoff: float = Field(..., example=0.0)
    stoploss: float = Field(..., example=0.0)
    trailingstoploss: float = Field(..., example=0.0)
    tradingsymbol: str = Field(..., example="BANKNIFTY29MAY24FUT")
    symboltoken: str = Field(..., example="46923")
    ordertag: str = Field(..., example="")
    strikeprice: float = Field(..., example=-1.0)
    optiontype: str = Field(..., example="XX")
    # TODO: try to use datetime.date
    expirydate: str = Field(..., example="29MAY2024")
    lotsize: float = Field(..., example="15")
    cancelsize: float = Field(..., example="0")
    averageprice: float = Field(..., example=0.0)
    filledshares: float = Field(..., example="0")
    unfilledshares: float = Field(..., example="15")
    orderid: str = Field(..., example="240527001860613")
    text: str = Field(
        ...,
        example="RMS:Rule: Position limit including CNC exceeds ,Current:15, limit set:1  for entity account-M57484244 across exchange across segment across product",
    )
    status: str = Field(..., example="rejected")
    orderstatus: str = Field(..., example="rejected")
    updatetime: datetime.datetime = Field(..., example="27-May-2024 22:17:54")
    exchtime: str = Field(..., example="")
    exchorderupdatetime: str = Field(..., example="")
    fillid: str = Field(..., example="")
    filltime: str = Field(..., example="")
    parentorderid: str = Field(..., example="")
    clientcode: str = Field(..., example="M57484244")

    class Config:
        populate_by_name = True
        use_enum_values = True
        example = {
            "variety": "NORMAL",
            "ordertype": "MARKET",
            "producttype": "CARRYFORWARD",
            "duration": "IOC",
            "price": 0.0,
            "triggerprice": 0.0,
            "quantity": "15",
            "disclosedquantity": "0",
            "squareoff": 0.0,
            "stoploss": 0.0,
            "trailingstoploss": 0.0,
            "tradingsymbol": "BANKNIFTY29MAY24FUT",
            "transactiontype": "BUY",
            "exchange": "NFO",
            "symboltoken": "46923",
            "ordertag": "",
            "instrumenttype": "FUTIDX",
            "strikeprice": -1.0,
            "optiontype": "XX",
            "expirydate": "29MAY2024",
            "lotsize": "15",
            "cancelsize": "0",
            "averageprice": 0.0,
            "filledshares": "0",
            "unfilledshares": "15",
            "orderid": "240527001860613",
            "text": "Adapter is Logged Off",
            "status": "rejected",
            "orderstatus": "rejected",
            "updatetime": "27-May-2024 22:17:54",
            "exchtime": "",
            "exchorderupdatetime": "",
            "fillid": "",
            "filltime": "",
            "parentorderid": "",
            "clientcode": "M57484244",
        }

    @field_validator("updatetime", mode="before")
    def parse_datetime(cls, value):
        if isinstance(value, datetime.datetime):
            return value
        try:
            return datetime.datetime.strptime(value, "%d-%b-%Y %H:%M:%S")
        except ValueError:
            raise ValueError(f"Unable to parse the datetime: {value}")
