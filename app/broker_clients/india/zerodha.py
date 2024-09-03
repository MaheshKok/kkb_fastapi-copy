import pyotp
import requests
from kiteconnect.connect import KiteConnect


class ZerodhoClient(KiteConnect):
    async def login_with_totp(self):
        pass


# TODO: in progress


def get_client(credentials: dict):
    # Code fetch from : https://www.youtube.com/watch?v=t5v4Xrz6JfY&t=3058s
    http_session = requests.Session()
    response = http_session.post(
        url="https://kite.zerodha.com/api/login",
        data={
            "user_id": credentials["username"],
            "password": credentials["password"],
        },
    )
    resp_dict = response.json()

    # TOTP POST request
    _ = http_session.post(
        url="https://kite.zerodha.com/api/twofa",
        data={
            "user_id": credentials["username"],
            "request_id": resp_dict["data"]["request_id"],
            "twofa_value": pyotp.TOTP(credentials["totp_key"]).now(),
            "twofa_type": "totp",
        },
    )

    client = ZerodhoClient(api_key=credentials["api_key"])
    login_url = client.login_url() + "&skip_session=true"
    try:
        _ = http_session.get(login_url)
        # return login_response.cookies.get("enctoken")
    except Exception as exc:
        request_token = exc.request.url.split("request_token=")[1].split("&")[0]
        _response = client.generate_session(request_token, api_secret=credentials["api_secret"])
        access_token = _response["access_token"]
        client.set_access_token(access_token)
        return client


# client = ZerodhoClient(api_key=credentials["api_key"])


credentials = {
    "username": "AZS228",
    "password": "Monsoonof2024",
    "api_key": "ljztg7an0ffcx7kh",
    "totp_key": "KLVEZEMQUKIMEHNEDDLFQHMS3VBPJMF6",
    "api_secret": "j1u0bguikvagnfc8s3kl7yn8afcl2ovj",
}
client = get_client(credentials=credentials)
print(client.orders())

access_token = "ijXHdC6KRQsXmOPucY6xr5ZW3rXCY3EZ"
