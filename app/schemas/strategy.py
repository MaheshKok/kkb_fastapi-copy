import uuid
from typing import Optional

from pydantic import BaseConfig
from pydantic import BaseModel
from pydantic import Field
from pydantic.json import UUID

from app.schemas.enums import InstrumentTypeEnum


class StrategyCreateSchema(BaseModel):
    class Config:
        orm_mode = True

    instrument_type: InstrumentTypeEnum = Field(
        description="Instrument Type", example=InstrumentTypeEnum.OPTIDX
    )
    symbol: str = Field(description="Symbol", example="BANKNIFTY")
    name: str = Field(description="Name", example="BANKNIFTY1! TF:2 Brick_Size:35 Pyramiding:100")
    broker_id: Optional[UUID] = Field(
        description="Broker on which strategy will be executed",
        example="6b38655e-0e28-471d-aefb-dd7ce2f6a825",
    )
    user_id: UUID = Field(
        description="User to which strategy belongs",
        example="fb90dd9c-9e16-4043-b5a5-18aacb42f726",
    )


class StrategySchema(StrategyCreateSchema):
    id: UUID = Field(description="Strategy ID", example="ff80cf6b-3c4a-4d28-82b0-631eafb4cdd1")

    class Config(BaseConfig):
        orm_mode = True
        json_encoders = {uuid.UUID: str}
