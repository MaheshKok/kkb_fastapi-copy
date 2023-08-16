from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class BrokerSchema(BaseModel):
    # create pydantic model for broker based on database model (BrokerModel)
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Broker ID", example="ff80cf6b-3c4a-4d28-82b0-631eafb4cdd1")
    access_token: str = Field(
        description="access token",
        example="u5tIkfvy1OgSPx1tvQ3e1XSHeml82qMQRuLszzVSBEsFevFElu87ZNP2A20zB4nu8Wfo8JSlYR2hgOUNzQAtppkABzlt7Um1Tke8znrt413hveAz9b4BFNDU2ob6KoK4RcXz3rRSkhPMr3QnO2Trxv3dBgldQT54FSnNq0UlWN3vNX7tKsBQ7Vxs1CZmFHrnx5SmdnA37gc8dbgbuRXGbbiFGn5c4kOHrQrIWtU0PTcJhX0riMdyvPYtk1e5A5AF",
    )
    name: str = Field(description="Name of broker", example="ALICEBLUE")
    username: str = Field(description="username", example="569619")
    password: str = Field(description="password", example="PASSword@123")
    api_key: str = Field(
        description="API Key",
        example="fsXFEAckBJ64gOY2Q23mGHaQdmNvfloCsPEjTHuMgdGMmxoHOaE4Sp18Ap20YUFyak8gOClPSHnLxGXPd3hZ57aGLvH85FBMQFzz",
    )
    app_id: str = Field(description="App Id", example="4EhBOEKf6ry5UXO")
    totp: str = Field(description="one time otp", example="OQJXYQYHSUVWXGAHUCENZPEGIFXUZFXA")
    twoFA: int = Field(description="birth year for alice blue", example=1994)
