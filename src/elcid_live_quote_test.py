"""Manual ELCID/Asian Paints live quote diagnostic.

No broker connection is created during pytest collection. Execute this file
explicitly when a live read-only connectivity check is desired.
"""


def main():
    import os
    from decimal import Decimal
    from dotenv import load_dotenv
    from src.broker.session_manager import SessionManager
    from src.broker.angel_client import AngelClient

    load_dotenv()
    api_key = os.getenv("ANGEL_API_KEY")
    client_id = os.getenv("ANGEL_CLIENT_ID")
    password = os.getenv("ANGEL_PASSWORD")
    totp_secret = os.getenv("ANGEL_TOTP_SECRET")
    if not all([api_key, client_id, password, totp_secret]):
        raise RuntimeError("Missing Angel One credentials in .env")

    instruments = [
        {"exchange": "NSE", "symbol": "ELCIDIN-EQ", "token": "762658"},
        {"exchange": "NSE", "symbol": "ASIANPAINT-EQ", "token": "236"},
    ]
    session_manager = SessionManager(api_key, client_id, password, totp_secret)
    client = AngelClient(session_manager.get_client(), session_manager=session_manager)

    print("PEREZ AI — READ-ONLY LIVE QUOTE CONNECTIVITY TEST")
    for instrument in instruments:
        response = client.get_ltp(instrument["exchange"], instrument["symbol"], instrument["token"])
        data = response.get("data") if isinstance(response, dict) else None
        if isinstance(data, dict):
            for key in ("ltp", "LTP", "close"):
                if data.get(key) is not None:
                    print(f"{instrument['symbol']}: Rs {Decimal(str(data[key])):,.2f}")
                    break
            else:
                raise RuntimeError(f"Could not extract LTP for {instrument['symbol']}: {response}")
        else:
            raise RuntimeError(f"No usable response for {instrument['symbol']}: {response}")


if __name__ == "__main__":
    main()
