import uuid
from datetime import date
from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from pydantic import Field

from app.schemas.enums import ActionEnum
from app.schemas.enums import OptionTypeEnum
from app.schemas.enums import PositionEnum


class TradePostSchema(BaseModel):
    quantity: int = Field(description="Quantity", example=25)
    future_received_entry_price: float = Field(description="Future Entry Price", example=40600.5)
    strategy_id: uuid.UUID = Field(
        description="Strategy ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3"
    )
    action: ActionEnum = Field(
        description="Action, if its BUY then option_type = CE and if its SELL then PE",
        example="BUY",
    )
    position: PositionEnum = Field(description="Position,", example="LONG")

    received_at: datetime = Field(
        description="Received At", example="2023-05-22 05:11:01.117358+00"
    )
    premium: Optional[float] = Field(description="Premium", example=350.0)
    strike: Optional[float] = Field(description="Strike", example=42500.0, default=0.0)

    class Config:
        orm_mode = True
        example = {
            "quantity": 25,
            "future_received_entry_price": 40600.5,
            "strategy_id": "0d478355-1439-4f73-a72c-04bb0b3917c7",
            "action": "BUY",
            "position": "LONG",
            "received_at": "2023-05-22 05:11:01.117358+00",
            "premium": 350.0,
        }


class TradeSchema(TradePostSchema):
    class Config:
        orm_mode = True

    id: uuid.UUID = Field(description="Trade ID", example="ff80cf6b-3c4a-4d28-82b0-631eafb4cdd1")

    entry_price: float = Field(description="Entry Price", example=350.5)
    exit_price: Optional[float] = Field(description="Exit Price", example=450.5)
    profit: Optional[float] = Field(description="Profit", example=2500.0)

    future_exit_price: Optional[float] = Field(description="Future Exit Price", example=40700.5)
    future_profit: Optional[float] = Field(description="Future Profit", example=2500.0)

    placed_at: str = Field(description="Placed At", example="2023-05-22 05:11:04.117358+00")
    exited_at: Optional[str] = Field(
        description="Exited At", example="2023-05-22 06:25:03.117358+00"
    )

    option_type: OptionTypeEnum = Field(description="Option Type", example="CE")
    expiry: date = Field(description="Expiry", example="2023-05-22")

    instrument: str = Field(description="Instrument name", example="BANKNIFTY27APR23FUT")
