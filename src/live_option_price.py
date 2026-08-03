from SmartApi import SmartConnect
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
import pyotp


def login():

    obj = SmartConnect(api_key=API_KEY)

    obj.generateSession(
        CLIENT_ID,
        PASSWORD,
        pyotp.TOTP(TOTP_SECRET).now()
    )

    return obj


def get_option_ltp(exchange, symbol, token):

    obj = login()

    response = obj.ltpData(
        exchange,
        symbol,
        token
    )

    if response["status"]:
        return float(response["data"]["ltp"])

    print(response)
    return None
