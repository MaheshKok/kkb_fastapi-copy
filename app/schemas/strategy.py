import uuid
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class StrategySchema(BaseModel):
    # create pydantic model for strategy based on database model (Strategy)
    class Config:
        orm_mode = True

    id: uuid.UUID = Field(
        description="Strategy ID", example="ff80cf6b-3c4a-4d28-82b0-631eafb4cdd1"
    )
    nfo_type: str = Field(description="NFO Type", example="FUTIDX")
    created_at: str = Field(description="Created At", example="2023-05-22 05:11:03.117358+00")
    symbol: str = Field(description="Symbol", example="BANKNIFTY")
    name: str = Field(description="Name", example="BANKNIFTY1! TF:2 Brick_Size:35 Pyramiding:100")
    broker_id: Optional[int] = Field(
        description="Broker ID", example="ff9acef9-e6c4-4792-9d43-d266b4d685c3"
    )
