import uuid
from datetime import date
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class TradeSchema(BaseModel):
    class Config:
        orm_mode = True

    id: uuid.UUID = Field(description="Trade ID", example="ff80cf6b-3c4a-4d28-82b0-631eafb4cdd1")
    quantity: int = Field(description="Quantity", example=25)
    entry_price: float = Field(description="Entry Price", example=350.5)
    exit_price: Optional[float] = Field(description="Exit Price", example=450.5)
    profit: Optional[float] = Field(description="Profit", example=2500.0)
    future_entry_price: float = Field(description="Future Entry Price", example=40600.5)
    future_exit_price: Optional[float] = Field(description="Future Exit Price", example=40700.5)
    future_profit: Optional[float] = Field(description="Future Profit", example=2500.0)
    placed_at: str = Field(description="Placed At", example="2023-05-22 05:11:03.117358+00")
    exited_at: Optional[str] = Field(
        description="Exited At", example="2023-05-22 06:25:03.117358+00"
    )
    strike: float = Field(description="Strike", example=42600.0)
    option_type: str = Field(description="Option Type", example="CE")
    expiry: date = Field(description="Expiry", example="2023-05-22")
    strategy_id: uuid.UUID = Field(
        description="Strategy ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3"
    )
