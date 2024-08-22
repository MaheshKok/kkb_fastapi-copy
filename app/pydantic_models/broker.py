from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from app.pydantic_models.enums import ExchangeEnum
from app.pydantic_models.enums import InstrumentTypeEnum


class BrokerPydModel(BaseModel):
    # create pydantic model for broker_clients based on a database model (BrokerModel)
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Broker ID", examples=["ff80cf6b-3c4a-4d28-82b0-631eafb4cdd1"])
    access_token: Optional[str] = Field(
        description="access token",
        default=None,
        examples=[
            "u5tIkfvy1OgSPx1tvQ3e1XSHeml82qMQRuLszzVSBEsFevFElu87ZNP2A20zB4nu8Wfo8JSlYR2hgOUNzQAtppkABzlt7Um1Tke8znrt413hveAz9b4BFNDU2ob6KoK4RcXz3rRSkhPMr3QnO2Trxv3dBgldQT54FSnNq0UlWN3vNX7tKsBQ7Vxs1CZmFHrnx5SmdnA37gc8dbgbuRXGbbiFGn5c4kOHrQrIWtU0PTcJhX0riMdyvPYtk1e5A5AF"
        ],
    )
    name: str = Field(description="Name of broker_clients", examples=["ALICEBLUE"])
    username: str = Field(description="username", examples=["569619"])
    password: str = Field(description="password", examples=["PASSword@123"])
    api_key: str = Field(
        description="API Key",
        examples=[
            "fsXFEAckBJ64gOY2Q23mGHaQdmNvfloCsPEjTHuMgdGMmxoHOaE4Sp18Ap20YUFyak8gOClPSHnLxGXPd3hZ57aGLvH85FBMQFzz"
        ],
    )
    app_id: Optional[str] = Field(
        description="App Id", examples=["4EhBOEKf6ry5UXO"], default=None
    )
    totp: str = Field(description="one time otp", examples=["OQJXYQYHSUVWXGAHUCENZPEGIFXUZFXA"])
    twoFA: Optional[int] = Field(
        description="birth year for alice blue", examples=[1994], default=None
    )
    refresh_token: Optional[str] = Field(
        description="refresh token", examples=["<KEY>"], default=""
    )
    feed_token: Optional[str] = Field(description="feed token", examples=["<KEY>"], default="")


class AngelOneInstrumentPydModel(BaseModel):
    exch_seg: ExchangeEnum = Field(..., examples=["NFO"], description="Exchange Segment")
    expiry: str = Field(..., examples=["27MAR2024"], description="Expiry Date")
    instrumenttype: InstrumentTypeEnum = Field(
        ..., examples=["OPTIDX"], description="Instrument Type"
    )
    lotsize: int = Field(..., examples=[15], description="Number of Shares per Lot")
    name: str = Field(..., examples=["BANKNIFTY"], description="Instrument Name")
    strike: float = Field(..., examples=[4770000.00], description="Strike Price")
    symbol: str = Field(..., examples=["BANKNIFTY27MAR2447700CE"], description="Ticker Symbol")
    tick_size: float = Field(..., examples=[5.00], description="Smallest Price Movement")
    token: int = Field(..., examples=[66716], description="Unique Identifier for the Instrument")
