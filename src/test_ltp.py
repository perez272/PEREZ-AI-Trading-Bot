from SmartApi import SmartConnect
from src.config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
import pyotp


obj = SmartConnect(api_key=API_KEY)

obj.generateSession(
    CLIENT_ID,
    PASSWORD,
    pyotp.TOTP(TOTP_SECRET).now()
)

symbol = "AXISBANK26JUL1240CE"
token = "1138612"

for exch in ["NFO", "NSE"]:

    print("\nTesting:", exch)

    try:
        result = obj.ltpData(
            exch,
            symbol,
            token
        )

        print(result)

    except Exception as e:
        print(e)
