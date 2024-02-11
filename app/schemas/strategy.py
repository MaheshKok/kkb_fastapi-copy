import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from typing_extensions import Self

from app.schemas.enums import InstrumentTypeEnum
from app.schemas.enums import PositionEnum


class StrategyCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_type: InstrumentTypeEnum = Field(
        description="Instrument Type", example=InstrumentTypeEnum.OPTIDX
    )
    symbol: str = Field(description="Symbol", example="BANKNIFTY")
    name: str = Field(description="Name", example="BANKNIFTY1! TF:2 Brick_Size:35 Pyramiding:100")
    position: PositionEnum = Field(description="Position", example="LONG")

    premium: Optional[float] = Field(description="Premium", example=350.0, default=None)

    funds: float = Field(description="Funds", example=1000000.0)
    future_funds: float = Field(description="Strategy Funds", example=100000.0)
    min_quantity: float = Field(description="Min Quantity", example=10)
    margin_for_min_quantity: float = Field(description="Margin for Min Quantity", example=2.65)
    incremental_step_size: float = Field(description="Incremental Step Size", example=0.1)
    compounding: bool = Field(description="Compounding")
    contracts: float = Field(description="Contracts", example=15)
    funds_usage_percent: float = Field(description="Funds Usage Percent", example=0.25)

    broker_id: Optional[uuid.UUID] = Field(
        description="Broker on which strategy will be executed",
        example="6b38655e-0e28-471d-aefb-dd7ce2f6a825",
        default=None,
    )
    user_id: uuid.UUID = Field(
        description="User to which strategy belongs",
        example="fb90dd9c-9e16-4043-b5a5-18aacb42f726",
    )

    @model_validator(mode="before")
    def basic_verification(_input) -> Self:
        if not isinstance(_input, dict):
            return _input

        if _input["instrument_type"] == InstrumentTypeEnum.FUTIDX:
            _input["premium"] = 0.0
        else:
            if not _input.get("premium"):
                raise ValueError("Premium is required for OPTIDX instruments")

        if _input["compounding"]:
            _input["contracts"] = 0.0
        else:
            if not _input.get("contracts"):
                raise ValueError("Contracts is required for not compounding strategy")

        return _input


class StrategySchema(StrategyCreateSchema):
    id: uuid.UUID = Field(
        description="Strategy ID", example="ff80cf6b-3c4a-4d28-82b0-631eafb4cdd1"
    )

    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})


class CFDStrategySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(
        description="Strategy ID", example="ff80cf6b-3c4a-4d28-82b0-631eafb4cdd1"
    )
    instrument: str = Field(description="Instrument", example="NATURALGAS")

    created_at: datetime = Field(description="Created At", example="2023-10-23:00:00.000000")
    updated_at: Optional[datetime] = Field(
        description="Updated At", example="2023-10-23:00:00.000000"
    )

    min_quantity: float = Field(description="Min Quantity", example=10)
    margin_for_min_quantity: float = Field(description="Margin for Min Quantity", example=2.65)
    incremental_step_size: float = Field(description="Incremental Step Size", example=0.1)
    max_drawdown: float = Field(description="Max Drawdown", example=0.25)

    is_active: bool = Field(description="Is Active", example=True)
    is_demo: bool = Field(description="Is Demo", example=True)
    funds: float = Field(description="Funds", example=100.0)
    name: str = Field(description="Name", example="Renko Strategy Every Candle")

    compounding: bool = Field(description="Compounding")
    contracts: Optional[float] = Field(description="Contracts", example=15, default=None)
    funds_usage_percent: float = Field(description="Funds Usage Percent", example=0.25)

    broker_id: Optional[uuid.UUID] = Field(
        description="Broker on which strategy will be executed",
        example="6b38655e-0e28-471d-aefb-dd7ce2f6a825",
        default=None,
    )
    user_id: uuid.UUID = Field(
        description="User to which strategy belongs",
        example="fb90dd9c-9e16-4043-b5a5-18aacb42f726",
    )
