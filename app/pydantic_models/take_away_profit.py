import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import condecimal


class TakeAwayProfitPydModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(
        description="Completed Profit ID", example="ff80cf6b-3c4a-4d28-82b0-631eafb4cdd1"
    )
    profit: condecimal(decimal_places=2) = Field(description="Profit", example=2500.0)
    future_profit: condecimal(decimal_places=2) = Field(
        description="Futures Profit", example=25000.5
    )
    strategy_id: uuid.UUID = Field(
        description="Strategy ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3"
    )
    created_at: datetime = Field(
        description="Created At", example="2023-05-22 05:11:03.117358+00"
    )
    updated_at: Optional[datetime] = Field(
        description="Updated At", example="2023-05-22 05:11:03.117358+00", default=None
    )
    total_trades: int = Field(description="Total Trades", example=1300)
