"""Optional live-quote utility.

Importing this module is side-effect free: no broker login, filesystem read,
or network request occurs until the explicit function is called.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv


def fetch_nifty_quote(instruments_path="data/instruments.json"):
    """Fetch the current NIFTY quote using the instrument master."""
    from SmartApi import SmartConnect
    import pyotp

    load_dotenv()
    obj = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
    session = obj.generateSession(
        os.getenv("ANGEL_CLIENT_ID"),
        os.getenv("ANGEL_PASSWORD"),
        pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now(),
    )
    if not session or not session.get("status"):
        raise RuntimeError("Angel One login failed")

    path = Path(instruments_path)
    if not path.exists():
        raise FileNotFoundError(f"Instrument master not found: {path}")
    instruments = json.loads(path.read_text())
    nifty = next(
        x for x in instruments
        if x.get("name") == "NIFTY"
        and x.get("symbol") == "Nifty 50"
        and x.get("exch_seg") == "NSE"
    )
    return obj.ltpData(nifty["exch_seg"], nifty["symbol"], nifty["token"])


if __name__ == "__main__":
    print(fetch_nifty_quote())
