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


class EntryExitEnum(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


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
    entry_exit: EntryExitEnum
    trade_id: Optional[uuid.UUID] = None


class InstrumentPydModel(BaseModel):
    class Config:
        use_enum_values = True

    exch_seg: ExchangeEnum = Field(..., alias="exch_seg", examples=["NFO"])
    expiry: str = Field(..., examples=["29MAY2024"])
    instrumenttype: InstrumentTypeEnum = Field(..., examples=["FUTIDX"])
    lotsize: int = Field(..., examples=[15])
    name: str = Field(..., examples=["BANKNIFTY"])
    strike: float = Field(..., examples=["-1.000000"])
    symbol: str = Field(..., examples=["BANKNIFTY29MAY24FUT"])
    tick_size: float = Field(..., examples=["5.000000"])
    token: str = Field(..., examples=["46923"])


class OrderDataPydModel(BaseModel):
    script: str = Field(..., examples=["BANKNIFTY29MAY24FUT"])
    orderid: str = Field(..., examples=["200910000000111"])
    uniqueorderid: uuid.UUID = Field(..., examples=["bcd193be-0bb6-476a-b397-a70376d166cb"])


class OrderResponsePydModel(BaseModel):
    status: Optional[bool] = Field(..., example=True)
    message: str = Field(..., examples=["SUCCESS"])
    errorcode: str = Field(..., examples=["AB1012"])
    data: OrderDataPydModel | None = Field(default=None)

    class Config:
        populate_by_name = True


class UpdatedOrderPydModel(OrderPayloadPydModel):
    price: float = Field(..., examples=[0.0])
    triggerprice: float = Field(..., examples=[0.0])
    quantity: float = Field(..., examples=["15"])
    disclosedquantity: str = Field(..., examples=["0"])
    squareoff: float = Field(..., examples=[0.0])
    stoploss: float = Field(..., examples=[0.0])
    trailingstoploss: float = Field(..., examples=[0.0])
    tradingsymbol: str = Field(..., examples=["BANKNIFTY29MAY24FUT"])
    symboltoken: str = Field(..., examples=["46923"])
    ordertag: str = Field(..., examples=[""])
    strikeprice: float = Field(..., example=-1.0)
    optiontype: str = Field(..., examples=["XX"])
    # TODO: try to use datetime.date
    expirydate: str = Field(..., examples=["29MAY2024"])
    lotsize: float = Field(..., examples=["15"])
    cancelsize: float = Field(..., examples=["0"])
    averageprice: float = Field(..., examples=[0.0])
    filledshares: float = Field(..., examples=["0"])
    unfilledshares: float = Field(..., examples=["15"])
    orderid: str = Field(..., examples=["240527001860613"])
    text: str = Field(
        ...,
        examples=[
            "RMS:Rule: Position limit including CNC exceeds ,Current:15, limit set:1  for entity account-M57484244 across exchange across segment across product"
        ],
    )
    status: str = Field(..., examples=["rejected"])
    orderstatus: str = Field(..., examples=["rejected"])
    updatetime: datetime.datetime = Field(..., examples=["27-May-2024 22:17:54"])
    exchtime: str = Field(..., examples=[""])
    exchorderupdatetime: str = Field(..., examples=[""])
    fillid: str = Field(..., examples=[""])
    filltime: str = Field(..., examples=[""])
    parentorderid: str = Field(..., examples=[""])
    clientcode: str = Field(..., examples=["M57484244"])

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
