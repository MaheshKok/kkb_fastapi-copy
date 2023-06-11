import uuid
from datetime import date
from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from pydantic import Field
from pydantic import root_validator

from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum


class TradePostSchema(BaseModel):
    quantity: int = Field(description="Quantity", example=25)
    future_received_entry_price: float = Field(description="Future Entry Price", example=40600.5)
    strategy_id: uuid.UUID = Field(
        description="Strategy ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3"
    )
    option_type: OptionTypeEnum = Field(
        description="Option Type",
        example="CE",
    )

    received_at: datetime = Field(description="Received At", example="2023-05-22 05:11:01.117358")
    premium: Optional[float] = Field(description="Premium", example=350.0)
    strike: Optional[float] = Field(description="Strike", example=42500.0, default=0.0)
    position: PositionEnum = Field(description="Position", example="LONG")

    class Config:
        orm_mode = True
        example = {
            "quantity": 25,
            "future_received_entry_price": 40600.5,
            "strategy_id": "0d478355-1439-4f73-a72c-04bb0b3917c7",
            "option_type": "CE",
            "position": "LONG",
            "received_at": "2023-05-22 05:11:01.117358",
            "premium": 350.0,
        }


class TradeSchema(TradePostSchema):
    class Config:
        orm_mode = True
        # Specify the fields to exclude
        exclude = {"premium"}

    entry_price: float = Field(description="Entry Price", example=350.5)
    exit_price: Optional[float] = Field(description="Exit Price", example=450.5)
    profit: Optional[float] = Field(description="Profit", example=2500.0)

    future_exit_price: Optional[float] = Field(description="Future Exit Price", example=40700.5)
    future_profit: Optional[float] = Field(description="Future Profit", example=2500.0)

    placed_at: str = Field(
        description="Placed At", default=datetime.now(), example="2023-05-22 05:11:04.117358+00"
    )
    exited_at: Optional[str] = Field(
        description="Exited At", example="2023-05-22 06:25:03.117358+00"
    )

    expiry: date = Field(description="Expiry", example="2023-05-22")

    instrument: str = Field(description="Instrument name", example="BANKNIFTY27APR23FUT")

    @root_validator(pre=True)
    def populate_instrument(cls, values):
        # even though we dont have a out symbol field,
        # it will be fetched from strategy and attached to the payload that will go in TradeSchema,
        return {
            **values,
            "instrument": f"{values['symbol']}{values['expiry'].strftime('%d%b%y').upper()}{values['strike']}{values['option_type']}",
        }
